# Chat Streaming And Run Cancel

## Cel

Repo-local celem backendu jest dostarczenie stabilnego kontraktu runtime i HTTP dla dwoch sciezek:
- streamowania odpowiedzi agenta przez SSE,
- kontrolowanego anulowania aktywnego runu.

Ta specyfikacja jest self-contained i opisuje backendowy zakres bez potrzeby czytania frontendu.

## Kontekst lokalny

Stan obecny backendu:
- `POST /api/v1/chat/completions` obsluguje `stream=true` i zwraca SSE z [api.py](../../src/app/api/v1/chat/api.py),
- `ChatService` ma sciezki `process_chat(...)`, `process_chat_stream(...)` i `process_delivery(...)` w [chat_service.py](../../src/app/services/chat_service.py),
- `Runner` umie `run_agent(...)`, `run_agent_stream(...)` i `deliver_result(...)` w [runner.py](../../src/app/runtime/runner.py),
- domena ma `AgentStatus.CANCELLED`, ale runtime i API chat nie maja realnego flow cancel,
- warstwa events nie ma jeszcze definicji `agent.cancelled`,
- provider i MCP nie dostaja wspolnego tokenu anulowania.

Powod tej zmiany teraz:
- frontend ma przejsc na streaming odpowiedzi,
- bez backendowego cancel `Stop` bylby tylko zamknieciem requestu, a nie kontrolowanym koncem runu.

## Scope

In-scope:
- kontrakt `cancel` w API chat,
- status `cancelled` w `ChatResponse`,
- rejestr aktywnych runow lub rownowazny wspoldzielony mechanizm cancellation coordination,
- cancellation-aware `Runner`,
- propagacja tokenu anulowania do:
  - providerow
  - tool registry
  - MCP clienta
- event `agent.cancelled`,
- testy backendowe dla runu anulowanego podczas streamingu i podczas non-stream flow.

Out-of-scope:
- kolejkowanie nowych wiadomosci podczas aktywnego runu,
- produktowe cancel dla stanu `waiting`,
- zmiany w sesjach user-facing poza tym, co wynika z nowego statusu root agenta,
- nowe provider-specific funkcje niezwiazane z anulowaniem.

## Kontrakt wejsciowy i wyjsciowy

### API z frontendem

`POST /api/v1/chat/completions`
- request:
  - jak dzisiaj,
  - `stream=true` pozostaje flaga aktywujaca SSE,
- response:
  - bez zmiany ksztaltu eventow SSE,
  - frontend po zakonczeniu streamu robi refetch sesji i szczegolow.

`POST /api/v1/chat/agents/{agent_id}/cancel`
- request body:
  - puste albo minimalne body techniczne; brak danych biznesowych od usera,
- response:
  - `ChatResponse`,
  - `status` po udanym anulowaniu: `cancelled`,
  - dla agenta juz terminalnego: aktualny stan terminalny bez dodatkowej mutacji.

`ChatResponse.status`
- musi dopuszczac:
  - `completed`
  - `waiting`
  - `failed`
  - `cancelled`

### API layer <-> runtime

API i service maja:
- zglosic chec anulowania aktywnego runu,
- poczekac na finalny wynik albo otrzymac juz gotowy stan terminalny,
- zwrocic `ChatResponse` bez pozostawiania agenta w `running`.

Runtime ma:
- zarejestrowac aktywny run przed rozpoczeciem pracy,
- regularnie sprawdzac token anulowania w petli runnera,
- przy anulowaniu ustawic `AgentStatus.CANCELLED`,
- wyemitowac `agent.cancelled`,
- posprzatac rejestr aktywnych runow i zadbac o brak wycieku stanu.

### Runtime <-> providers/tools/MCP

Wymagany jest wspolny token anulowania dla:
- `Provider.generate(...)`,
- `Provider.stream(...)`,
- `ToolRegistry.execute(...)`,
- `McpManager.call_tool(...)`.

Implementacja moze byc cooperative:
- provider/tool/MCP powinny reagowac jak najszybciej,
- jesli nie da sie twardo przerwac operacji natychmiast, runner i tak musi dojsc do `cancelled` przy pierwszym bezpiecznym punkcie.

## Moduly do zmiany

API i schemy:
- `src/app/api/v1/chat/api.py`
- `src/app/api/v1/chat/schema.py`

Service:
- `src/app/services/chat_service.py`

Runtime:
- `src/app/runtime/runner.py`
- nowy modul w runtime lub services dla cancellation registry, np. `src/app/runtime/cancellation.py`

Container i DI:
- `src/app/container.py`

Providers:
- `src/app/providers/base.py`
- `src/app/providers/types.py`
- `src/app/providers/openrouter_provider.py`

Tools i MCP:
- `src/app/tools/registry.py`
- `src/app/mcp/client.py`

Events:
- `src/app/events/definitions/agent_cancelled.py`
- `src/app/events/definitions/__init__.py`
- ewentualne subscriber-y obserwowalnosci, jesli wymagaja nowego eventu

Testy:
- `src/tests/test_chat_service.py`
- `src/tests/test_sessions_api.py`
- nowe albo rozszerzone testy runnera i streamingu

## Oczekiwane zachowanie

### Flow non-stream

1. `run_agent(...)` startuje jak dzisiaj.
2. Gdy w trakcie pracy pojawi sie sygnal cancel:
   - runner nie przechodzi do `failed`,
   - zapisuje `cancelled`,
   - emituje `agent.cancelled`,
   - zwraca `RunResult` ze statusem `cancelled`.

### Flow streaming

1. `run_agent_stream(...)` uruchamia ten sam runtime co non-stream.
2. Dopoki run trwa, SSE wypycha eventy providera.
3. Gdy przyjdzie cancel:
   - provider stream konczy sie kontrolowanie,
   - backend zamyka SSE bez pozostawiania sesji w `running`,
   - stan agenta po stronie persistence jest `cancelled`.

### Flow `cancel`

1. Drugi request HTTP wskazuje `agent_id` do anulowania.
2. Service znajduje aktywny run i sygnalizuje cancellation token.
3. Runner konczy run jako `cancelled`.
4. Endpoint zwraca aktualny `ChatResponse`.

### Delegacja

Jesli cancel dotyczy root agenta w trakcie delegacji:
- root agent ma zakonczyc sie jako `cancelled`,
- child runy uruchomione w ramach tego samego aktywnego execution flow nie moga zostac osierocone w stanie `running`,
- szczegoly produktu dla niezaleznego cancel child agentow sa poza zakresem; wystarczy spojnosc runtime dla aktualnego aktywnego drzewa.

## Decyzje architektoniczne

- Nie polegamy tylko na przerwaniu requestu SSE.
- Nie traktujemy cancel jako `failed`.
- Nie budujemy osobnego runtime dla streamingu.
- Nie wprowadzamy wymagan na nowe zmienne env.
- Rejestr cancellation powinien byc singletonem w kontenerze, bo ma laczyc wiele requestow HTTP.

## Edge cases

- cancel przychodzi po naturalnym `completed`: endpoint zwraca aktualny stan terminalny, bez bledu produktowego,
- cancel przychodzi dla `waiting`: backend moze zwrocic aktualny stan bez mutacji; pelny waiting-cancel jest poza zakresem,
- provider nie wspiera natychmiastowego abort: runner konczy przy najblizszym bezpiecznym punkcie i cleanup nadal jest wymagany,
- stream zrywa sie po stronie klienta bez wywolania `cancel`: brak gwarancji anulowania; oficjalna sciezka produktu to jawny endpoint `cancel`.

## Acceptance Criteria

- `ChatResponse.status` obsluguje `cancelled`,
- istnieje endpoint `POST /api/v1/chat/agents/{agent_id}/cancel`,
- aktywny run przechodzi do `cancelled`, a nie `failed`,
- po anulowaniu agent nie zostaje w `running`,
- `run_agent_stream(...)` i `run_agent(...)` przechodza przez ten sam cleanup cancellation,
- event `agent.cancelled` jest emitowany i nie psuje obecnej observability,
- backendowe testy obejmuja co najmniej cancel dla:
  - aktywnego runu non-stream
  - aktywnego runu stream
  - idempotentnego wywolania na stanie terminalnym

## Test plan

- testy jednostkowe:
  - cancellation registry,
  - runner cancellation w petli turnow,
  - cleanup aktywnego runu po cancellation,
  - mapowanie `cancelled` do `RunResult` i `ChatResponse`.
- testy integracyjne:
  - `POST /chat/completions` ze `stream=true` + rownolegly `POST /cancel`,
  - `POST /chat/completions` ze `stream=false` + cancellation-aware runner,
  - `POST /cancel` dla agenta juz `completed`.
- test manualny:
  - uruchomic dluzszy stream,
  - wywolac cancel,
  - sprawdzic baze i szczegoly sesji,
  - sprawdzic brak pozostawionego `running`.

## Handoff: planner

Done:
- Zdefiniowano backendowy kontrakt `stream + cancel`.
- Wskazano konkretne moduly wymagajace zmian i wymagania dla runtime cleanup.

Contract:
- Backend dostarcza `cancelled` jako stan terminalny.
- API chat zyskuje endpoint `cancel`, a SSE zachowuje obecny ksztalt eventow.

Next role:
- `manfred_backend`

Risks:
- Najtrudniejsza czesc to wspoldzielony coordination layer dla aktywnego runu oraz propagacja anulowania do providera i MCP.
