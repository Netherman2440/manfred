# Plan implementacji tool types `agent` i `human`

Ten dokument zbiera kontekst i proponuje plan wdrozenia dwoch dodatkowych typow narzedzi w `manfred`:

- `agent` - delegacja zadania do innego agenta,
- `human` - przerwanie petli i wejscie w human-in-the-loop.

Pierwszymi narzedziami w tych typach maja byc:

- `delegate(agent_name, task)`,
- `ask_user(question)`.

Zakres dokumentu obejmuje aktualny stan `manfreda`, referencje do dzialajacego przykladu z `4th-devs/01_05_agent` oraz kolejnosc zmian potrzebnych do wdrozenia tego flow w Pythonie.

## Referencje

- Runner: [`src/app/runtime/runner.py`](../src/app/runtime/runner.py)
- Typy narzedzi: [`src/app/domain/tool.py`](../src/app/domain/tool.py)
- Domena agenta: [`src/app/domain/agent.py`](../src/app/domain/agent.py)
- Repozytorium agenta: [`src/app/domain/repositories/agent_repository.py`](../src/app/domain/repositories/agent_repository.py)
- Chat service: [`src/app/services/chat_service.py`](../src/app/services/chat_service.py)
- Schemy API chat: [`src/app/api/v1/chat/schema.py`](../src/app/api/v1/chat/schema.py)
- Loader agentow: [`src/app/services/agent_loader.py`](../src/app/services/agent_loader.py)
- Kontener DI: [`src/app/container.py`](../src/app/container.py)
- Referencja TS runnera: `4th-devs/01_05_agent/src/runtime/runner.ts`
- Referencja TS toola `delegate`: `4th-devs/01_05_agent/src/tools/definitions/delegate.ts`
- Referencja TS toola `ask_user`: `4th-devs/01_05_agent/src/tools/definitions/ask-user.ts`
- Referencja TS domeny agenta: `4th-devs/01_05_agent/src/domain/agent.ts`
- Referencja TS typow oczekiwania: `4th-devs/01_05_agent/src/domain/types.ts`

## Stan obecny w `manfred`

### Co juz jest gotowe

- `ToolType` w [`src/app/domain/tool.py`](../src/app/domain/tool.py) zna juz wartosci `sync`, `async`, `agent`, `human`.
- `AgentStatus` w [`src/app/domain/types.py`](../src/app/domain/types.py) zawiera juz `WAITING`.
- `Runner` w [`src/app/runtime/runner.py`](../src/app/runtime/runner.py) obsluguje petle tur, zapis itemow, eventy, MCP i sync tools.
- `Agent` ma juz pola potrzebne do hierarchii delegacji: `root_agent_id`, `parent_id`, `depth`, `agent_name`.
- `ItemRepository` ma juz `list_by_agent_after_sequence(...)`, co przyda sie do zwracania nowych itemow po wznowieniu.

### Gdzie sa luki

- `Runner.handle_turn_response(...)` obsluguje dzis tylko `sync` oraz fallback MCP. Kazdy inny `tool.type` konczy ture bledem: `Tool type '...' is not implemented yet.`
- `Runner.run_agent(...)` zwraca obecnie blad dla agenta w stanie `WAITING`, zamiast zwracac stan oczekiwania.
- `Agent` i `AgentModel` nie przechowuja jeszcze:
  - `waiting_for`,
  - `source_call_id`,
  - opcjonalnie utrwalonego `result` albo `error`.
- `ChatResponse` w [`src/app/api/v1/chat/schema.py`](../src/app/api/v1/chat/schema.py) dopuszcza tylko status `completed` albo `failed`.
- W API nie ma jeszcze endpointu `deliver`.
- `container.py` rejestruje obecnie tylko `calculator`.
- `AgentLoader` umie zaladowac agenta po sciezce, ale nie ma jeszcze jawnej metody rozwiązywania child agenta po nazwie, co jest potrzebne dla `delegate(agent_name, task)`.

## Zachowanie referencyjne z `4th-devs/01_05_agent`

### `delegate`

W referencji TS tool `delegate`:

- ma `type: 'agent'`,
- ma handler walidacyjny, ale nie wykonuje delegacji samodzielnie,
- przekazuje realna logike do runnera.

W runnerze delegacja:

- waliduje argumenty,
- sprawdza limit glebokosci,
- laduje child agent template po nazwie,
- tworzy child agenta w tej samej sesji,
- ustawia `rootAgentId`, `parentId`, `sourceCallId`, `depth`,
- dopisuje `task` jako wiadomosc `user` do historii dziecka,
- rekurencyjnie uruchamia `runAgent(...)`,
- po sukcesie zapisuje `function_call_output` na parentcie,
- po `waiting` childa przenosi parenta do `waiting`,
- po bledzie zwraca error jako `function_call_output`.

### `ask_user`

W referencji TS tool `ask_user`:

- ma `type: 'human'`,
- ma handler walidacyjny,
- nie wykonuje nic synchronicznie,
- powoduje przejscie agenta do `waiting`.

Runner dopisuje do `waitingFor` wpis:

- `callId`,
- `type: 'human'`,
- `name`,
- `description`, zwykle oparte o `question`.

### `deliver`

W referencji TS `deliverResult(...)`:

- dopisuje `function_call_output` dla oczekujacego `callId`,
- usuwa odpowiedni wpis z `waitingFor`,
- emituje `agent.resumed`,
- jesli nadal sa zaleglosci, agent zostaje w `waiting`,
- jesli wszystkie zaleglosci zniknely, runner znowu wchodzi w `runAgent(...)`,
- jesli zakonczony child ma `parentId` i `sourceCallId`, wynik dziecka propaguje sie automatycznie do parenta.

## Docelowy kontrakt dla `manfreda`

### 1. Narzedzia

Pierwsze dwa narzedzia wbudowane:

- `delegate`
  - `type = "agent"`
  - argumenty: `agent_name: str`, `task: str`
- `ask_user`
  - `type = "human"`
  - argumenty: `question: str`

Wazne: referencja TS uzywa pola `agent`, ale w `manfredzie` kontrakt powinien zostac nazwany `agent_name`, zgodnie z obecnym zalozeniem produktu. Nie warto wspierac obu nazw w pierwszej wersji, bo to rozwadnia schemat i prompting.

### 2. Stan oczekiwania

`Agent` powinien miec utrwalona liste oczekiwan, np. jako `waiting_for: list[WaitingForEntry]`.

Minimalny ksztalt pojedynczego wpisu:

- `call_id: str`
- `type: Literal["tool", "agent", "human"]`
- `name: str`
- `description: str | None`

To powinno trafic do domeny i do bazy, a nie pozostac tylko efemerycznie w `TurnResult`.

### 3. Delegacja child agenta

Do poprawnej delegacji parent agent musi zapisac w child agencie:

- `session_id`,
- `root_agent_id`,
- `parent_id`,
- `source_call_id`,
- `depth`,
- `agent_name`,
- `config` wynikajacy z child template.

### 4. Resume przez `deliver`

System musi wspierac osobny flow:

- API dostarcza wynik dla `agent_id` i `call_id`,
- runtime zapisuje `function_call_output`,
- agent wychodzi z `waiting` albo zostaje w nim, jesli nadal czegos brakuje,
- gdy wszystkie oczekiwania sa spelnione, runner kontynuuje petle.

## Rekomendowany zakres implementacji

Zeby nie rozlewac zmian po calym runtime naraz, rekomendowany jest taki zakres pierwszego wdrozenia:

1. Pelne wsparcie `delegate` i `ask_user` w trybie non-streaming.
2. `run_agent(...)` oraz `execute_chat(...)` maja umiec zwrocic status `waiting`.
3. Dodac `deliver` dla human/delegation resume.
4. Streaming doprowadzic do parity po ustabilizowaniu wspolnych helperow runnera.

To daje dzialajace `human in the loop` i delegacje bez ryzyka, ze pierwsza iteracja ugrzeznie na SSE albo dodatkowych typach deferred tools.

## Plan implementacji

### Etap 1. Rozszerzyc model domenowy agenta

Pliki:

- `src/app/domain/agent.py`
- `src/app/db/models/agent.py`
- `src/app/domain/repositories/agent_repository.py`
- nowa migracja Alembica

Zmiany:

- dodac `source_call_id: str | None`,
- dodac `waiting_for: list[WaitingForEntry]`,
- opcjonalnie dodac `result: str | None` i `last_error: str | None`, jesli chcesz miec stan bardziej zblizony do referencji.

Minimalna rekomendacja na teraz:

- `source_call_id` oraz `waiting_for` sa wymagane,
- `result` i `last_error` mozna odlozyc, bo `manfred` juz trzyma wynik w itemach i bledy w `RunResult`.

Uwaga projektowa:

- `waiting_for` powinno byc osobnym polem JSON w tabeli `agents`, nie czescia `config`.
- `config` opisuje konfiguracje agenta, a `waiting_for` jest stanem runtime.

### Etap 2. Wprowadzic typ domenowy `WaitingForEntry`

Pliki:

- nowy modul, np. `src/app/domain/waiting.py`
- albo rozszerzenie `src/app/domain/types.py`

Potrzebne rzeczy:

- dataclass albo `TypedDict` dla wpisu oczekiwania,
- wspolna serializacja/deserializacja dla repozytorium,
- spójny mapping do API.

Rekomendacja:

- uzyc dataclass z polami `call_id`, `type`, `name`, `description`,
- trzymac mapping JSON lokalnie w `AgentRepository`.

### Etap 3. Dodac dwa narzedzia wbudowane

Pliki:

- `src/app/tools/definitions/delegate.py`
- `src/app/tools/definitions/ask_user.py`
- `src/app/container.py`

Semantyka:

- oba handlery robia tylko walidacje argumentow i ewentualny normalizowany output pomocniczy,
- realna logika pozostaje w runnerze,
- oba toole musza zostac dodane do `get_tools()`.

Rekomendowany kontrakt handlerow:

- `delegate` zwraca `{ "ok": True, "output": "{\"agent_name\": ..., \"task\": ...}" }` po walidacji,
- `ask_user` zwraca `{ "ok": True, "output": question }` po walidacji.

To zachowuje zgodnosc z wzorcem z referencji TS i ulatwia testy argumentow.

### Etap 4. Rozszerzyc `AgentLoader` o rozwiązywanie agenta po nazwie

Pliki:

- `src/app/services/agent_loader.py`
- ewentualnie `src/app/config.py`

Potrzebne zachowanie:

- `delegate(agent_name, task)` musi umiec zaladowac child template po nazwie, a nie po pelnej sciezce.

Najprostsza strategia:

- uznac katalog `WORKSPACE_PATH/agents`,
- mapowac `agent_name="bob"` na `WORKSPACE_PATH/agents/bob.agent.md`,
- wystawic helper w stylu `load_agent_by_name(agent_name: str) -> LoadedAgent`.

To jest zgodne z aktualnym `DEFAULT_AGENT` i nie wymaga osobnej bazy definicji agentow.

### Etap 5. Rozszerzyc kontrakt runnera o `waiting`

Pliki:

- `src/app/runtime/runner.py`

Zmiany w typach pomocniczych:

- `TurnResult.status` powinien wspierac `waiting`,
- `RunResult.status` powinien wspierac `waiting`,
- `RunResult` powinien zwracac `agent` rowniez dla `waiting`,
- `TurnResult` powinien przenosic `waiting_for`.

Zmiany w `run_agent(...)`:

- jesli agent jest juz `WAITING`, zwrocic `RunResult(ok=True, status="waiting", ...)`,
- po zakonczeniu tury obsluzyc przejscie do `WAITING` zamiast traktowac je jak blad,
- nie emitowac `AgentCompletedEvent`, jesli run konczy sie w `waiting`.

Zmiany w `handle_turn_response(...)`:

- zbudowac lokalna liste `waiting_for`,
- dla `tool.type == "human"` dopisac wpis `type="human"`,
- dla `tool.type == "agent"` wywolac wydzielony helper delegacji,
- jesli po obsludze function calli `waiting_for` nie jest puste:
  - ustawic `agent.status = WAITING`,
  - zapisac `agent.waiting_for`,
  - zwrocic `TurnResult(status="waiting", ...)`.

Wazne:

- obecny fallback dla MCP i `sync` powinien zostac bez zmian,
- `ask_user` nie powinien zapisywac `function_call_output` przed `deliver`,
- `delegate` zapisuje `function_call_output` tylko wtedy, gdy child skonczyl synchronicznie albo zwrocil blad.

### Etap 6. Wydzielic helper delegacji w runnerze

Pliki:

- `src/app/runtime/runner.py`

Rekomendowany helper:

```python
async def _handle_agent_function_call(
    self,
    context: AgentRunContext,
    *,
    function_call: ProviderFunctionCallOutputItem,
) -> DelegationResult: ...
```

Kroki helpera:

1. Zweryfikowac argumenty `agent_name` i `task`.
2. Sprawdzic limit glebokosci delegacji.
3. Zaladowac template dziecka przez `AgentLoader`.
4. Utworzyc child agenta z `parent_id`, `root_agent_id`, `source_call_id`, `depth + 1`.
5. Dodac do historii dziecka wiadomosc `user` z trescia `task`.
6. Rekurencyjnie wywolac `run_agent(child_id, last_agent_sequence=0, ...)`.
7. Rozgalezienie wyniku:
   - `completed` -> zapisac `function_call_output` na parentcie i kontynuowac,
   - `waiting` -> zwrocic wpis `WaitingForEntry(type="agent", ...)`,
   - `failed` -> zapisac blad jako `function_call_output`,
   - `cancelled` -> potraktowac jako blad delegacji.

Rekomendacja:

- nie wpychac tej logiki do `ToolRegistry.execute(...)`,
- delegacja to zachowanie runtime, nie zwyklego tool handlera.

### Etap 7. Dodac `deliver`

Pliki:

- `src/app/runtime/runner.py`
- `src/app/services/chat_service.py`
- `src/app/api/v1/chat/schema.py`
- `src/app/api/v1/chat/api.py`

Potrzebny kontrakt runtime:

```python
async def deliver_result(
    self,
    agent_id: str,
    *,
    call_id: str,
    result: dict[str, Any],
) -> RunResult: ...
```

Minimalne zachowanie:

- znalezc agenta i sprawdzic `WAITING`,
- zapisac `function_call_output`,
- usunac wpis z `waiting_for`,
- jesli sa jeszcze zaleglosci, zwrocic `waiting`,
- jesli nie ma zaleglosci, ustawic `RUNNING` i uruchomic `run_agent(...)` ponownie.

Do tego trzeba dolozyc:

- request/response schema dla `deliver`,
- endpoint `POST /api/v1/chat/agents/{agent_id}/deliver`.

### Etap 8. Rozszerzyc API chat o status `waiting`

Pliki:

- `src/app/api/v1/chat/schema.py`
- `src/app/services/chat_service.py`
- `src/app/api/v1/chat/api.py`

Minimalne zmiany:

- `ChatResponse.status` powinien dopuszczac `waiting`,
- `ChatResponse` powinien miec `waiting_for`,
- `ChatService.execute_chat(...)` powinien mapowac `RunResult(status="waiting")` bez traktowania tego jako bledu.

To jest konieczne, bo bez tego `ask_user(...)` bedzie mial runtime, ktory wszedl w `WAITING`, ale warstwa HTTP nie bedzie umiala tego zwrocic.

### Etap 9. Doprowadzic eventy do parity z nowym flow

Pliki:

- `src/app/events/definitions/`
- `src/app/events/__init__.py`
- `src/app/runtime/runner.py`

Do dodania:

- `agent.waiting`,
- `agent.resumed`,
- opcjonalnie `agent.cancelled`, jesli chcesz domknac lifecycle rownolegle.

Minimalny moment emisji:

- `agent.waiting` po zapisaniu `waiting_for`,
- `agent.resumed` po `deliver`, gdy przynajmniej jeden `call_id` zostal dostarczony.

### Etap 10. Doprowadzic streaming do parity

Pliki:

- `src/app/runtime/runner.py`

Obecnie `run_agent_stream(...)` duplikuje znaczna czesc logiki `run_agent(...)`.
Po dodaniu `waiting` i delegacji trzeba dopilnowac, zeby oba flow:

- obslugiwaly identyczne branche narzedzi,
- jednakowo aktualizowaly status agenta,
- jednakowo emitowaly eventy.

Najbezpieczniejsza kolejnosc:

- najpierw wdrozyc non-streaming,
- potem zrefaktorowac wspolne helpery tak, by streaming tylko konsumowal juz istniejace zachowania.

## Kolejnosc wdrozenia

Rekomendowana kolejnosc prac:

1. Migracja bazy i domeny: `source_call_id`, `waiting_for`, `WaitingForEntry`.
2. Dodanie `delegate.py` i `ask_user.py` oraz rejestracja w `container.py`.
3. `AgentLoader.load_agent_by_name(...)`.
4. Rozszerzenie `Runner.run_agent(...)` i `handle_turn_response(...)` o `waiting`.
5. Implementacja helpera delegacji.
6. Implementacja `deliver`.
7. Rozszerzenie API response/request schema.
8. Eventy `agent.waiting` i `agent.resumed`.
9. Streaming parity.

## Plan testow

Minimalny zestaw testow:

- runner: `ask_user` przeprowadza agenta do `waiting` i zapisuje `waiting_for`,
- runner: `delegate` tworzy child agenta i zapisuje sukces jako `function_call_output`,
- runner: `delegate` propaguje `waiting`, gdy child czeka na czlowieka,
- runner: `delegate` zwraca blad, gdy child template nie istnieje,
- runner: limit glebokosci delegacji konczy sie kontrolowanym bledem,
- runtime: `deliver` usuwa pojedynczy wpis z `waiting_for` i wznawia run po ostatnim brakujacym wyniku,
- api/chat service: odpowiedz `ChatResponse` poprawnie zwraca status `waiting` i `waiting_for`.

## Otwarte decyzje

### 1. Czy wspierac oba pola `agent` i `agent_name` w `delegate`

Rekomendacja: nie.

Powod:

- uzytkowy kontrakt ma byc jasny,
- schema toola powinna odpowiadac temu, czego oczekujemy w promptach i testach,
- ewentualny adapter kompatybilnosci mozna dodac pozniej, jesli pojawi sie realna potrzeba.

### 2. Skad brac finalny wynik child agenta

Rekomendacja:

- dla pierwszej wersji uzyc tej samej semantyki co obecny runner, czyli ostatniej wiadomosci `assistant` zapisanej po `last_agent_sequence`.

To jest wystarczajace do `delegate`, a bardziej formalne pole `result` mozna dolozyc pozniej, jesli bedzie potrzebne dla API statusowego.

### 3. Czy `ask_user` ma od razu wymagac nowego endpointu statusowego

Rekomendacja: nie blokowac wdrozenia na `GET /agents/{id}`.

Do minimalnego dzialania wystarcza:

- `POST /chat/completions`,
- `POST /chat/agents/{agent_id}/deliver`.

Status endpoint mozna dolozyc jako krok nastepny.
