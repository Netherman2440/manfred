# Plan implementacji `runner.py`

Ten dokument rozpisuje etap 2 migracji przykładu `4th-devs/01_05_agent` do `manfreda`.
Zakres tego etapu obejmuje runtime agenta, provider LLM i obsluge tur.
Plan zaklada prostszy pierwszy przebieg niz w referencyjnym TypeScripcie: najpierw petla z providerem i sync tools, a dopiero pozniej bardziej zlozone scenariusze.

## Referencje

- TS runner: `/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts`
- Dokument wysokopoziomowy: `/home/netherman/code/manfred/docs/agent_loop.md`
- Etap 1: `/home/netherman/code/manfred/docs/chat_service_plan.md`
- Docelowy plik: `/home/netherman/code/manfred/src/app/runtime/runner.py`

## Cel etapu

Na koniec tego etapu `manfred` ma umiec:

- zaladowac kontekst wykonania agenta: `agent`, `session`, `items`,
- wejsc w petle `run_agent(...)`,
- w kazdej iteracji wykonac `execute_turn(...)`,
- przygotowac input dla providera na podstawie historii itemow,
- pobrac odpowiedz od providera,
- zapisac odpowiedz AI do repozytoriow,
- wykonac wszystkie sync toole zwrocone przez model,
- zapisac wyniki tooli jako itemy,
- kontynuowac petle, dopoki model zwraca tool calle,
- zakonczyc wykonanie, gdy agent zwroci finalna odpowiedz do uzytkownika.

Na tym etapie runner ma byc gotowy do pracy z `ChatService.execute_chat(...)`.

## Docelowy kontrakt runnera

W `/home/netherman/code/manfred/src/app/runtime/runner.py` warto wprowadzic klase `Runner` z trzema glownymi metodami:

```python
class Runner:
    async def run_agent(self, agent_id: str, *, max_turns: int = 10) -> RunResult: ...
    async def execute_turn(self, context: AgentRunContext) -> TurnResult: ...
    async def handle_turn_response(
        self,
        context: AgentRunContext,
        response: ProviderResponse,
    ) -> TurnResult: ...
```

`run_agent(...)` odpowiada za petle.
`execute_turn(...)` odpowiada za przygotowanie requestu do modelu i wywolanie providera.
`handle_turn_response(...)` odpowiada za zapis outputu i wykonanie tooli.

## Zakladany pierwszy zakres funkcjonalny

Etap 2 powinien byc prostszy niz pelny `runner.ts`.
Rekomendowany pierwszy zakres:

- jeden provider LLM za wspolnym interfejsem, konkretnie OpenRouter,
- tylko tryb nie-streaming,
- tylko lokalne tools z `ToolRegistry`,
- tylko synchroniczne wykonanie tooli,
- brak `deliver`,
- brak `waiting`,
- brak delegacji child agentow,
- brak MCP.

To jest najmniejszy sensowny kawalek, ktory uruchomi cala petle i nie zabetonuje architektury.

Dodatkowe zalozenie dla etapu 2:

- pierwszym i jedynym providerem ma byc OpenRouter,
- mimo to interfejs ma od razu trafic do `/home/netherman/code/manfred/src/app/providers`,
- runner ma zalezec od luznego kontraktu providera, a nie od implementacji OpenRoutera.

## Braki w obecnym stanie `manfreda`

Przed implementacja runnera trzeba uwzglednic kilka luk w obecnym kodzie:

- `/home/netherman/code/manfred/src/app/runtime/runner.py` jest pusty,
- w repo nie ma jeszcze pakietu `providers`,
- katalogi `/home/netherman/code/manfred/src/app/events`, `/home/netherman/code/manfred/src/app/mcp` i `/home/netherman/code/manfred/src/app/tools` sa puste,
- obecny `Agent` nie przechowuje jeszcze pol przydatnych dla runnera, np. usage czy started_at,
- `AgentConfig` trzyma `task`, wiec runner powinien konsekwentnie korzystac z `agent.config.task`, a nie z nieistniejacego `agent.task`.

To nie blokuje etapu 2, ale trzeba to jawnie uwzglednic w implementacji.

## Plan implementacji

### 1. Dodac minimalna abstrakcje providera

Etap 2 wymaga nowego pakietu, np.:

- `/home/netherman/code/manfred/src/app/providers/base.py`
- `/home/netherman/code/manfred/src/app/providers/types.py`
- `/home/netherman/code/manfred/src/app/providers/registry.py`
- `/home/netherman/code/manfred/src/app/providers/openrouter_provider.py`

Minimalne typy:

- `Provider`
- `ProviderRequest`
- `ProviderResponse`
- `ProviderOutputItem`
- `ProviderUsage`

Pierwsza wersja nie musi wspierac streamingu.
Wystarczy kontrakt `generate(request) -> ProviderResponse`.

Istotne doprecyzowanie:

- na etapie 2 implementujemy tylko `OpenRouterProvider`,
- interfejs i typy maja byc jednak projektowane tak, zeby kolejne providery dalo sie dolozyc bez zmiany runnera.

### 2. Ustalic wspolny format input/output providera

Runner nie powinien pracowac bezposrednio na surowych strukturach SDK.
Potrzebny jest wspolny model posredni.

Minimalny input:

- `message`
- `function_call`
- `function_call_output`

Minimalny output:

- `text`
- `function_call`

To wystarczy do podstawowej petli agentowej.

### 3. Dolozyc provider registry do runtime

`Runner` powinien dostawac provider przez wstrzykniety registry albo resolver, a nie tworzyc klienta ad hoc.

Rekomendacja:

- model w `AgentConfig.model` trzymac docelowo w formacie `provider:model`,
- dla etapu 2 wspieramy tylko prefiks `openrouter:`,
- resolver wybiera providera po prefiksie,
- runner dostaje juz rozwiazany provider i nazwe modelu docelowego.

To zachowuje kierunek ze `spec.md`, ale nie wymaga od razu wielu implementacji providerow.

### 4. Doprecyzowac stan domenowy agenta

Do minimalnej petli wystarczy obecny `status` i `turn_count`, ale runner bedzie czytelniejszy, jesli dolozymy jeszcze:

- `started_at: datetime | None`
- `completed_at: datetime | None`
- `last_error: str | None`
- `usage_input_tokens: int`
- `usage_output_tokens: int`

Rekomendacja:

- nie pchac tego od razu do etapu 1,
- ale w etapie 2 zdecydowac, czy dodajemy te pola juz teraz, czy odkładamy usage na osobny krok.

Minimalne wymaganie do wdrozenia:

- agent musi umiec przechodzic przez `pending -> running -> completed/failed`.

### 5. Wprowadzic `AgentRunContext`

Runner nie powinien przekazywac luznych parametrow miedzy funkcjami.
Potrzebna jest jedna struktura robocza, np.:

```python
@dataclass(slots=True)
class AgentRunContext:
    agent: Agent
    session: Session
    items: list[Item]
```

W pierwszej wersji to wystarczy.
Jesli pozniej dojdzie tracing albo eventy, ten kontekst latwo rozszerzyc.

### 6. Zaimplementowac `load_agent_context`

`run_agent(agent_id)` powinno zaczynac od:

- zaladowania agenta,
- zaladowania sesji,
- zaladowania itemow tego agenta,
- walidacji spojnosci danych.

Jesli czegos brakuje:

- brak agenta -> blad wykonania,
- brak sesji -> blad integralnosci,
- brak itemow -> legalny stan dla nowego agenta.

### 7. Zaimplementowac `run_agent`

Glowna petla powinna wygladac logicznie tak:

```python
context = await self.load_agent_context(agent_id)
context.agent = mark_running(context.agent)

while context.agent.status == AgentStatus.RUNNING:
    turn = await self.execute_turn(context)
    context.agent = turn.agent

    if turn.status == "continue":
        context = await self.reload_context(context.agent.id)
        continue

    if turn.status == "completed":
        return ...

    if turn.status == "failed":
        return ...
```

Wazne zasady:

- `max_turns` ma chronic przed nieskonczona petla,
- po kazdej turze zapisujemy zmiany agenta,
- po kazdej turze odswiezamy itemy z repozytorium,
- runner konczy sie sukcesem dopiero, gdy agent ma finalna odpowiedz bez kolejnych tool calli.

Na tym etapie event bus nie jest jeszcze implementowany.
Zamiast tego w miejscach odpowiadajacych referencji TS warto dodac komentarze orientacyjne, np.:

```python
# agent.started
# turn.started
# generation.completed
# turn.completed
# agent.completed
# agent.failed
```

Te komentarze maja zaznaczyc punkty integracji pod przyszly system eventow, bez rozbudowywania teraz runtime'u o obserwowalnosc.

### 8. Zaimplementowac `execute_turn`

`execute_turn(...)` powinno:

- zmapowac itemy domenowe do wejscia providera,
- zbudowac `ProviderRequest` z `model`, `task`, `tools`, `temperature`,
- wywolac `provider.generate(...)`,
- przekazac wynik do `handle_turn_response(...)`.

Tu warto trzymac jednoznaczna odpowiedzialnosc:

- `execute_turn` nie zapisuje jeszcze odpowiedzi recznie,
- `handle_turn_response` decyduje, co trafia do repo i czy petla ma isc dalej.

### 9. Zmapowac itemy do inputu modelu

Potrzebny jest osobny helper, np. `map_items_to_provider_input(items)`.

Mapowanie minimalne:

- `ItemType.MESSAGE` -> `message`,
- `ItemType.FUNCTION_CALL` -> `function_call`,
- `ItemType.FUNCTION_CALL_OUTPUT` -> `function_call_output`,
- `ItemType.REASONING` na razie pomijamy.

W tej wersji nie robimy jeszcze pruning ani summary.
To sa rozszerzenia po uruchomieniu podstawowej petli.

### 10. Zapisywac output providera jako itemy

Potrzebny jest helper typu `store_provider_output(...)`.

Minimalne zasady:

- sklejony tekst modelu zapisujemy jako jedna wiadomosc `assistant`,
- kazdy `function_call` zapisujemy jako osobny item,
- sequence musi rosnac wewnatrz agenta,
- wszystko zapisujemy przed wykonaniem tooli.

To jest wazne, bo historia narzedziowa ma byc kompletna i replikowalna.

### 11. Zaimplementowac `handle_turn_response`

To jest serce etapu 2.

Logika pierwszej wersji:

1. Zapisz output providera.
2. Znajdz wszystkie `function_call`.
3. Jesli ich nie ma:
   ustaw agenta na `completed` i zakoncz ture.
4. Jesli sa:
   wykonaj je po kolei przez `ToolRegistry`.
5. Kazdy wynik narzedzia zapisz jako `function_call_output`.
6. Jesli wszystkie toole zakonczyly sie lokalnie:
   zwroc `continue`, zeby agent dostal kolejna ture z nowym kontekstem.

W pierwszej wersji nie rozgaleziamy jeszcze narzedzi po typach `human/agent/async`.
Jesli rejestr zawiera inny typ niz `sync`, runner powinien zwrocic czytelny blad `not implemented`.

### 12. Ustalic zasade finalnej odpowiedzi

Runner ma jechac dalej, dopoki model wykonuje narzedzia.
Zatrzymujemy sie dopiero wtedy, gdy odpowiedz nie zawiera juz `function_call`.

Rekomendacja:

- finalna odpowiedz dla uzytkownika to ostatni `assistant message`,
- obecny `ChatService.execute_chat(...)` filtruje potem widoczne itemy po `last_sequence`.

To dobrze rozdziela odpowiedzialnosc:

- runner odpowiada za stan i petle,
- chat service odpowiada za ksztalt odpowiedzi HTTP.

### 13. Obsluzyc bledy wykonania

Minimalna polityka bledow:

- brak providera -> `failed`,
- blad providera -> `failed`,
- blad wykonania toola:
  - zapisujemy `function_call_output` z `is_error=True`,
  - kontynuujemy petle, zeby model mogl zareagowac na blad narzedzia,
- przekroczenie `max_turns` -> `failed` z czytelnym komunikatem.

To odpowiada praktyce z referencji TS: tool failure nie musi od razu zabijac calego agenta.

W `run_agent(...)` i powiazanych helperach warto tez komentarzami oznaczyc miejsca, w ktorych w przyszlosci wejda eventy z referencji TypeScript, ale bez implementowania ich logiki w etapie 2.

### 14. Wpiac `Runner` do `ChatService`

Po wdrozeniu etapu 2 `ChatService.execute_chat(...)` nie powinno juz uzywac stuba.
Ma wywolywac:

```python
result = await self.runner.run_agent(agent_id)
```

A potem:

- pobierac itemy agenta,
- filtrowac je po `last_sequence`,
- budowac `ChatResponse`.

### 15. Dodac testy etapu 2

Minimalny zestaw testow:

- `run_agent` przechodzi `pending -> running -> completed`,
- runner konczy po samej odpowiedzi assistanta bez tool calli,
- runner wykonuje sync tool i robi kolejna ture,
- blad toola zapisuje `function_call_output` z `is_error=True` i nie zrywa petli od razu,
- blad providera ustawia `failed`,
- `max_turns` chroni przed petla nieskonczona,
- output providera jest poprawnie zapisywany jako itemy,
- mapowanie historii do providera uwzglednia `message`, `function_call`, `function_call_output`.

## Kolejnosc pracy

Rekomendowana kolejnosc wdrozenia:

1. Dodac typy providera i prosty registry.
2. Dodac pierwszy provider zgodny z nowym kontraktem.
3. Zaimplementowac `Runner.load_agent_context`.
4. Zaimplementowac `map_items_to_provider_input`.
5. Zaimplementowac `store_provider_output`.
6. Zaimplementowac `handle_turn_response` tylko dla sync tools.
7. Zaimplementowac `run_agent` z `max_turns`.
8. Podpiac `Runner` pod `ChatService.execute_chat`.
9. Dopisac testy.

## Kryteria akceptacji etapu 2

Etap uznajemy za zamkniety, gdy:

- `ChatService.execute_chat(...)` korzysta juz z prawdziwego runnera,
- runner laduje `agent`, `session` i `items`,
- provider dostaje ujednolicony input,
- output AI jest zapisywany do repozytorium,
- sync toole sa wykonywane i ich wynik wraca do historii,
- agent potrafi wykonac wiecej niz jedna ture,
- petla konczy sie po finalnej odpowiedzi dla uzytkownika,
- bledy providera i limity tur maja jawne zachowanie.

## Poza zakresem pierwszej wersji runnera

Tego dokumentu nie nalezy czytac jako planu pelnej kopii `runner.ts`.
W pierwszej wersji runnera celowo odkladamy:

- kolejnych providerow poza OpenRouterem,
- streaming,
- `deliver`,
- `waiting`,
- `human tools`,
- `agent delegation`,
- MCP,
- pruning,
- summarization,
- event bus i tracing,
- auto-propagation wynikow child agentow.

Te elementy maja wejsc dopiero po stabilnym uruchomieniu podstawowej petli `provider -> tools -> kolejna tura`.
