# Plan wdrożenia pętli subagentów w `manfred`

## Cel

Przenieść do `manfred` mechanikę subagentów inspirowaną `4th-devs/01_05_agent`, ale dopasowaną do obecnej architektury backendu:

- definicje agentów tylko po stronie backendu,
- template'y agentów trzymane w `workspace/agents/*.agent.md`,
- wsparcie dla `delegate`, `send_message`, `waiting`, `deliver`, `resume`,
- brak implementacji eventów i streamingu na tym etapie,
- zostawianie w kodzie krótkich `TODO` pod przyszłe eventy.

## Stan obecny w `manfred`

Obecna implementacja ma już fundamenty, ale nadal jest single-agent:

- `AgentRunner` obsługuje wyłącznie `sync` tools i nie ma ścieżki `waiting` ani `deliver`.
- `Agent` ma statusy `pending/running/waiting/completed/failed/cancelled`, ale domena faktycznie używa dziś tylko prostego ciągu `pending -> running -> completed/failed`.
- `AgentConfig` jest singletonem z kontenera i bierze prompt z jednego pliku `src/app/agent/prompts/system_prompt.md`.
- DB trzyma `root_agent_id`, `parent_id` i `depth`, ale brakuje `source_call_id` oraz `waiting_for`.
- API `chat/completions` zwraca tylko `completed` albo `failed`.

To oznacza, że największa praca nie dotyczy samych tooli, tylko przejść stanu i wznowienia pętli.

## Docelowe założenie

W etapie pierwszym odtwarzamy semantykę z `01_05_agent`, czyli:

- `delegate` jest narzędziem blokującym z punktu widzenia parenta,
- child agent uruchamia własną pętlę,
- jeśli child kończy się od razu, parent dostaje zwykły `function_call_output`,
- jeśli child przechodzi do `waiting`, parent także przechodzi do `waiting`,
- `POST /deliver` dostarcza wynik do oczekującego agenta,
- jeśli wznowiony child zakończy się i ma `parent_id + source_call_id`, wynik automatycznie propaguje się do parenta.

To jest najprostszy i najbardziej wierny wariant.

Dodatkowe doprecyzowanie dla tego etapu:

- nie wdrażamy pętli dosyłania wiadomości do pracującego agenta,
- nie wdrażamy mailbox-driven resume,
- `waiting` oznacza wyłącznie oczekiwanie na wynik toola albo na zewnętrzne `deliver`,
- `send_message` pozostaje zwykłym zapisem wiadomości do historii innego agenta i nie jest częścią mechanizmu wznawiania.
- przy obecnym zakresie projektu, gdzie używamy wyłącznie logiki synchronicznej, `deliver` będzie głównie gotową ścieżką infrastrukturalną pod przyszłe `human` i `async/deferred` tools, a nie czymś często używanym od razu po wdrożeniu.

## Ważna luka projektowa

Jest jeden istotny problem względem Twojego celu "follow up messages do subagentów":

- w modelu `01_05_agent` `delegate` jest blokujący,
- więc parent po wejściu childa w `waiting` sam przechodzi do `waiting`,
- a agent w stanie `waiting` nie może już sam z siebie wykonać kolejnego `send_message`.

W praktyce oznacza to, że:

- `send_message` jest przydatne dla agentów działających równolegle albo sterowanych z zewnątrz,
- ale nie rozwiązuje samo z siebie follow-upów od parenta do childa w blokującym `delegate`.

Rekomendacja:

- etap 1: wdrożyć wierną, blokującą delegację,
- etap 2: jeśli follow-upy parent -> child mają być realne, dodać osobną semantykę typu `spawn_agent` albo `delegate_async`.

Mimo to warto już teraz dodać do `waiting_for` metadane childa, np. `agent_id`, bo to będzie potrzebne do przyszłego sterowania.

## Template'y agentów

Docelowo rezygnujemy z jednego `SYSTEM_PROMPT_PATH` i przechodzimy na workspace:

- `workspace/agents/mandfred.agent.md`
- `workspace/agents/azazel.agent.md`

Na tym etapie frontend nic nie ustawia. Backend sam wybiera root template i jego toolset.

## Zakres implementacji

### 1. Loader template'ów agentów

Dodać loader czytający `workspace/agents/*.agent.md`.

Minimalny kontrakt template'u:

- `name`
- opcjonalnie `model`
- `tools`
- body markdown jako `system_prompt`

Rekomendowana ścieżka:

- nowy moduł typu `src/app/workspace/agents.py`

Odpowiedzialności loadera:

- wczytać plik markdown,
- sparsować frontmatter,
- zwrócić wewnętrzny `AgentTemplate`,
- rozwiązać `tool_names -> ToolDefinition[]` przez `ToolRegistry`,
- zwrócić błąd, jeśli template nie istnieje albo wskazuje nieznany tool.

Uwaga implementacyjna:

- Python nie ma YAML frontmatter parsera w stdlib,
- najprościej będzie dodać zależność `PyYAML`,
- alternatywnie można napisać minimalny parser własny dla prostego frontmatteru.

Rekomenduję `PyYAML`, bo plan zakłada więcej niż jeden template.

### 2. Refactor konfiguracji agenta

Obecny singleton `agent_config` w kontenerze trzeba zastąpić mechaniką template'ów.

Zmiany:

- usunąć zależność `ChatService` od jednego globalnego `AgentConfig`,
- dodać w `Settings`:
  - `ROOT_AGENT_TEMPLATE`
  - `AGENT_TEMPLATES_DIR`
  - `SUBAGENT_MAX_TURNS`
  - `MAX_AGENT_DEPTH`
- opcjonalnie zostawić `SYSTEM_PROMPT_PATH` tymczasowo tylko dla backward compatibility, ale nie używać go w nowej ścieżce.

`ConversationContextService` powinien:

- ładować root template po nazwie z configu,
- tworzyć root agenta z configiem wynikającym z template'u,
- przy kolejnym turnie resetować root agenta do `pending`,
- nie pozwalać frontendowi podmieniać modelu ani tooli.

### 3. Rozszerzenie domeny agenta

Potrzebne nowe pola i przejścia stanu.

W domenie dodać:

- `WaitingFor`
- `WaitType = tool | agent | human`
- `source_call_id`
- `waiting_for`
- opcjonalnie `result` i `error`

Rekomendowany minimalny model `WaitingFor`:

- `call_id`
- `type`
- `name`
- `description`
- `agent_id: str | None = None`

To ostatnie pole nie jest konieczne do wiernej kopii `01_05_agent`, ale bardzo pomaga pod Twoje przyszłe follow-upy.

Przejścia stanu do dodania w `domain/agent.py`:

- `prepare_agent_for_next_turn(...)`
- `start_agent(...)`
- `wait_for_many(...)`
- `deliver_one(...)`
- `complete_agent(...)`
- `fail_agent(...)`
- `cancel_agent(...)`

Zasady:

- `pending -> running`
- `running -> waiting`
- `waiting -> running` po dostarczeniu ostatniego wyniku
- `running -> completed/failed/cancelled`
- jeśli agent jest już `waiting`, zwykłe `run_agent(...)` ma zwracać stan oczekiwania zamiast ruszać dalej

### 4. Migracja DB i repozytoriów

Tabela `agents` wymaga rozszerzenia.

Do dodania:

- `source_call_id`
- `waiting_for` jako JSON
- opcjonalnie `result`
- opcjonalnie `error`

Zmiany obejmą:

- `src/app/db/models/agent.py`
- `src/app/db/repositories/agent_repository.py`
- nową migrację Alembica

Repozytorium powinno też dostać pomocniczą metodę typu:

- `find_waiting_by_call_id(call_id: str) -> Agent | None`

Nie jest ona wymagana do podstawowego `/deliver` po `agent_id`, ale później może uprościć wznowienia i diagnostykę.

### 5. Tool `delegate`

Dodać nowy tool:

- `src/app/agent/tools/delegate.py`

Kontrakt:

- `type="agent"`
- `name="delegate"`
- argumenty:
  - `agent`
  - `task`

Sam handler może być prawie no-opem i służyć tylko do walidacji, tak jak w `01_05_agent`.

Właściwa logika dzieje się w runnerze:

- sprawdzenie depth guard,
- załadowanie template'u childa,
- utworzenie child agenta,
- zapis taska jako `user` item childa,
- rekurencyjne `run_agent(child.id, ...)`,
- jeśli child zakończy się synchronicznie:
  - zapis `function_call_output` na parentcie,
- jeśli child przejdzie do `waiting`:
  - dodanie wpisu `WaitingFor(type="agent", ...)` do parenta,
- jeśli child padnie:
  - zapis błędu jako `function_call_output(is_error=True)`.

Do configu:

- `SUBAGENT_MAX_TURNS`
- `MAX_AGENT_DEPTH`

### 6. Tool `send_message`

Dodać nowy tool:

- `src/app/agent/tools/send_message.py`

Kontrakt:

- `type="sync"`
- `name="send_message"`
- argumenty:
  - `to`
  - `message`

Semantyka jak w `01_05_agent`:

- tool zapisuje `system` message do historii target agenta,
- nie zmienia statusu targeta,
- nie wybudza go automatycznie,
- zapisuje `function_call_output` na senderze.

Na tym etapie planu:

- nie budujemy osobnej pętli "agent pracuje i równolegle dostaje nowe wiadomości",
- nie budujemy endpointu do dosyłania zwykłych wiadomości jako mechanizmu sterowania runtime,
- `send_message` traktujemy wyłącznie jako prosty zapis kontekstu do odczytu w przyszłej turze target agenta.

Runner powinien interceptować ten tool po nazwie, bo sam handler nie ma dostępu do repozytoriów.

Ważne:

- `to` powinno przyjmować `agent_id`, nie nazwę template'u,
- jeśli w przyszłości chcesz follow-upy do childa przez API lub UI, to właśnie `agent_id` musi być widoczny w `waiting_for`.

### 7. Runner: obsługa `tool.type == agent`

To jest centralna zmiana.

`AgentRunner` trzeba przebudować z prostego loopa sync tools do pełnej pętli:

1. `run_agent(agent_id)`:
   - ładuje agenta i sesję,
   - jeśli `pending`, przełącza na `running`,
   - jeśli `waiting`, zwraca `RunResult(status="waiting")`,
   - pętla działa dopóki agent jest `running` i nie przekroczył limitu tur.

2. `execute_turn(...)`:
   - przygotowuje input do providera,
   - woła model,
   - zapisuje output,
   - deleguje do `handle_turn_response(...)`.

3. `handle_turn_response(...)`:
   - zbiera `function_calls`,
   - obsługuje:
     - `sync`
     - `agent`
     - `human` w przyszłości
     - deferred w przyszłości
   - zwraca:
     - `continue`
     - albo `waiting`
     - albo `error`

4. jeśli są wpisy `waiting_for`:
   - agent przechodzi do `waiting`,
   - runner kończy bez dalszego loopa,
   - `ChatService` zwraca status `waiting`.

W kodzie od razu warto zostawić komentarze:

- `# TODO: emit turn.started event here`
- `# TODO: emit tool.completed event here`
- `# TODO: emit agent.waiting event here`

Bez implementacji event busa.

### 8. `deliver` i `resume`

Potrzebny nowy flow wznowienia:

- `POST /api/v1/chat/agents/{agent_id}/deliver`

Payload:

- `callId`
- `output`
- `isError`

Semantyka:

1. sprawdzić, czy agent istnieje i jest w `waiting`,
2. dopisać `function_call_output`,
3. usunąć odpowiedni wpis z `waiting_for`,
4. jeśli nadal coś czeka:
   - zwrócić status `waiting`,
5. jeśli wszystko dostarczono:
   - ustawić agenta na `running`,
   - ponownie wywołać `run_agent(agent_id)`.

Auto-propagacja:

- jeśli wznowiony child zakończy się `completed`
- i ma `parent_id` oraz `source_call_id`
- runner automatycznie wywołuje `deliver_result(parent_id, source_call_id, child_output)`

To pozwala odtworzyć najważniejszą zaletę `01_05_agent`: parent nie polling-uje childa.

To jest też jedyny mechanizm wznowienia, który planujemy w tym etapie:

- agent wraca z `waiting` tylko po dostarczeniu oczekiwanego wyniku,
- oczekiwany wynik pochodzi z `tool result` albo z endpointu `deliver`,
- zwykłe wiadomości nie zmieniają stanu `waiting` i nie wznawiają pętli.

Praktyczna uwaga dla obecnego `manfreda`:

- dopóki nie ma realnych tooli `human` ani `async/deferred`, wejście w `waiting` będzie rzadkie,
- sam endpoint `/deliver` warto mimo to wdrożyć teraz, bo domyka model stanu i upraszcza późniejsze dodanie takich tooli bez przebudowy runnera i API.

### 9. API i kontrakty odpowiedzi

Zmieni się `ChatResponse`.

Potrzebne:

- `status: completed | waiting | failed`
- `waitingFor?: []`

Rekomendowany minimalny shape `waitingFor`:

- `callId`
- `type`
- `name`
- `description`
- `agentId?`

`POST /chat/completions`:

- `200` gdy `completed`
- `202` gdy `waiting`

Warto dodać także:

- `GET /api/v1/chat/agents/{agent_id}`

żeby łatwo podejrzeć:

- `status`
- `waiting_for`
- `turn_count`
- `depth`
- `parent_id`
- `root_agent_id`

### 10. Chat service

`ChatService` wymaga dwóch zmian:

1. ścieżka standardowa:
   - `prepare_chat_turn(...)`
   - `process_chat(...)`
   - odpowiedź z `completed` albo `waiting`

2. ścieżka deliver:
   - nowa metoda typu `deliver_result(...)`
   - używana przez endpoint `/deliver`

Ważne:

- `prepare_chat_turn(...)` powinno nadal tworzyć tylko user item dla root agenta,
- child agenci są tworzeni wyłącznie z poziomu runnera,
- frontend nadal nie przekazuje żadnego configu agenta.

### 11. Rejestracja tooli i template'ów

`container.py` trzeba zmienić tak, żeby:

- rejestrował `delegate_tool`,
- rejestrował `send_message_tool`,
- budował loader template'ów agentów,
- przekazywał runnerowi:
  - loader,
  - `SUBAGENT_MAX_TURNS`,
  - `MAX_AGENT_DEPTH`

Tool registry nadal pozostaje globalny, ale agent template ogranicza, które definicje są wystawiane modelowi.

### 12. Testy

Minimalny pakiet testów:

- test loadera markdown template'ów,
- test `delegate` walidacji argumentów,
- test `send_message` walidacji argumentów,
- test domeny przejść:
  - `running -> waiting`
  - `waiting -> running`
- test runnera:
  - child kończy się synchronicznie,
  - child przechodzi do `waiting`,
  - parent przechodzi do `waiting`,
  - `deliver` wznawia childa,
  - auto-propagacja child -> parent,
  - `send_message` zapisuje `system` item w target agencie,
- test API:
  - `POST /chat/completions` zwraca `202`,
  - `POST /chat/agents/{id}/deliver` wznawia pętlę,
  - `GET /chat/agents/{id}` pokazuje status.

## Proponowana kolejność implementacji

### Etap 1. Template loader i konfiguracja root agenta

- dodać `workspace/agents`
- dodać loader template'ów
- przełączyć `ChatService` i `ConversationContextService` z jednego promptu na root template

Rezultat:

- root agent działa z pliku markdown zamiast z `system_prompt.md`

### Etap 2. Domena i migracja DB

- dodać `waiting_for`
- dodać `source_call_id`
- dodać pełne przejścia stanu

Rezultat:

- agent może legalnie wejść w `waiting` i wrócić do `running`

### Etap 3. Tool `delegate` i runner branch dla `agent`

- dodać definicję toola
- dodać `handle_delegation(...)`
- dodać `MAX_AGENT_DEPTH` i `SUBAGENT_MAX_TURNS`

Rezultat:

- root agent może uruchomić childa

### Etap 4. Tool `send_message`

- dodać tool
- dodać intercept w runnerze

Rezultat:

- agenci mogą przekazywać sobie kontekst przez `system` messages

### Etap 5. `deliver` i auto-resume

- dodać endpoint
- dodać service method
- dodać `deliver_result(...)` w runnerze
- dodać auto-propagację child -> parent

Rezultat:

- pełna pętla `waiting/resume`

### Etap 6. API statusów

- rozszerzyć `ChatResponse`
- dodać `GET /agents/{id}`
- dodać `202 Accepted` dla waiting

Rezultat:

- frontend ma pełny snapshot stanu agenta

### Etap 7. Testy domykające

- testy domeny
- testy runnera
- testy API

Rezultat:

- subagenci są bezpiecznie refaktorowalni

## Rekomendowane pliki do zmiany

- `src/app/config.py`
- `src/app/container.py`
- `src/app/domain/agent.py`
- `src/app/domain/chat.py`
- `src/app/domain/types.py`
- `src/app/db/models/agent.py`
- `src/app/db/repositories/agent_repository.py`
- `src/app/runtime/runner.py`
- `src/app/services/conversation_context.py`
- `src/app/services/chat_service.py`
- `src/app/api/v1/chat/schema.py`
- `src/app/api/v1/chat/api.py`
- `src/app/agent/tools/__init__.py`
- nowe:
  - `src/app/agent/tools/delegate.py`
  - `src/app/agent/tools/send_message.py`
  - `src/app/workspace/agents.py`
  - migracja Alembica

## Czego nie robić w tym etapie

- nie dodawać frontendowych override'ów modelu, promptu ani tooli,
- nie wdrażać event busa,
- nie wdrażać streamingu,
- nie dodawać MCP,
- nie mieszać semantyki blokującego `delegate` z równoległym `spawn_agent`,
- nie wdrażać mailbox loop ani follow-up message loop do pracującego agenta,
- nie traktować `send_message` jako mechanizmu resume.

## Gotowe template'y startowe

W tym commicie startowe definicje agentów są przygotowane pod docelową strukturę:

- `workspace/agents/mandfred.agent.md`
- `workspace/agents/azazel.agent.md`

`mandfred` jest głównym agentem z toolami filesystem oraz narzędziami orkiestracji.

`azazel` jest prostym specjalistą od obrazów i audio.

## Podsumowanie rekomendacji

Najbezpieczniejsza ścieżka to:

1. przełączyć `manfred` na template'y markdown,
2. dołożyć pełną semantykę `waiting/deliver`,
3. dopiero potem dołożyć delegację child agentów,
4. zostawić `send_message` jako transport kontekstu, ale nie traktować go jeszcze jako rozwiązania follow-upów parent -> waiting child.

Jeśli follow-upy parent -> child mają być centralnym use-case'em, po zakończeniu tego etapu trzeba zaplanować drugą iterację z nieblokującą delegacją.
