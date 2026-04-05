# Plan implementacji streamingu SSE dla `POST /api/chat/completions`

Ten dokument rozpisuje plan wdrozenia streamingu odpowiedzi w `manfredzie`.
Zakres obejmuje:

- SSE po stronie HTTP,
- kontrakt streamingu po stronie providerow,
- sciezke streamingowa w `chat_service.py`,
- sciezke streamingowa w `runner.py`,
- mapowanie streamingu OpenRouter do wspolnych eventow,
- testy i kolejnosc wdrozenia.

Plan celowo rozdziela:

- eventy observability z `EventBus`,
- eventy streamingu zwracane klientowi przez SSE.

`EventBus` pozostaje warstwa obserwowalnosci.
SSE ma byc transportem dla request-scoped eventow runtime/providera, a nie adapterem na globalny bus.

## Referencje

- HTTP API: `src/app/api/v1/chat/api.py`
- API schema: `src/app/api/v1/chat/schema.py`
- Chat service: `src/app/services/chat_service.py`
- Runner: `src/app/runtime/runner.py`
- Provider base: `src/app/providers/base.py`
- Provider types: `src/app/providers/types.py`
- OpenRouter provider: `src/app/providers/openrouter_provider.py`
- Event bus: `src/app/events/event_bus.py`
- Referencja TS HTTP: `/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.ts`
- Referencja TS service: `/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.service.ts`
- Referencja TS runner: `/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts`
- Referencja TS provider types: `/home/netherman/code/4th-devs/01_05_agent/src/providers/types.ts`
- Referencja TS provider adapter: `/home/netherman/code/4th-devs/01_05_agent/src/providers/openai/adapter.ts`

## Cel etapu

Na koniec tego etapu `manfred` ma umiec:

- przyjac `stream=true` dla `POST /api/chat/completions`,
- zwracac odpowiedz jako `text/event-stream`,
- emitowac znormalizowane eventy streamingu niezalezne od konkretnego providera,
- wykonywac te sama petle runtime co w trybie non-stream,
- wypychac delty tekstu i function calli na biezaco,
- wysylac finalne `done` po kazdej zakonczonej odpowiedzi providera,
- zachowac zapis itemow, tool execution i eventy observability tak jak dzisiaj.

## Poza zakresem

Ten etap nie obejmuje:

- przeniesienia wykonania agenta do background workerow,
- pollingowego modelu statusowego zamiast SSE,
- streamowania przez `EventBus`,
- nowych eventow `waiting/resumed`,
- streamingu dla innych providerow niz OpenRouter,
- zmian UX po stronie frontendu poza kontraktem eventow.

## Stan obecny w `manfred`

Aktualny stan kodu:

- `ChatRequest` ma pole `stream`, ale endpoint zwraca `501`,
- `chat_service.py` odrzuca `stream=True` juz na etapie `prepare_chat(...)`,
- kontrakt providera ma tylko `generate(...)`,
- `ProviderStreamEvent` jeszcze nie istnieje,
- `Runner` ma tylko sciezke `run_agent(...)` i `execute_turn(...)`,
- `OpenRouterProvider` wykonuje tylko zwykle `POST /chat/completions`,
- `EventBus` jest juz wdrozony, ale nie powinien stac sie zrodlem danych dla SSE.

Wniosek praktyczny:

- brakuje pionowego slice'a `provider.stream -> runner.run_agent_stream -> chat_service.stream_prepared_chat -> FastAPI SSE`.

## Zasady architektoniczne

### 1. SSE nie jest adapterem na `EventBus`

Nie nalezy budowac streamingu HTTP przez subskrypcje na globalnym `EventBus`.

Powody:

- `EventBus` jest globalny, a stream HTTP jest request-scoped,
- bus jest warstwa observability, nie sterowania odpowiedzia API,
- delty tekstu i function calli powstaja najnizej, po stronie providera,
- laczenie SSE z bussem komplikuje korelacje, buforowanie i cleanup.

Decyzja:

- zrodlem prawdy dla SSE sa `ProviderStreamEvent`,
- `EventBus` dalej sluzy loggerowi i Langfuse.

### 2. Streaming ma miec ten sam runtime co tryb non-stream

Sciezka streamingowa nie powinna implementowac osobnej logiki tooli ani zapisu itemow.

Decyzja:

- `run_agent_stream(...)` ma korzystac z tej samej logiki `handle_turn_response(...)`,
- streaming rozni sie tylko transportem eventow providera i sposobem zwracania wyniku do klienta.

### 3. Kontrakt eventow ma byc provider-agnostic

FastAPI ani frontend nie powinny znac eventow natywnych OpenRouter/OpenAI.

Decyzja:

- provider mapuje natywne SSE/API eventy do wspolnego `ProviderStreamEvent`.

### 4. `done` jest eventem obowiazkowym

`done` warto wdrozyc od pierwszej wersji.

Semantyka:

- `done` oznacza zakonczenie jednej odpowiedzi providera,
- niesie pelny, znormalizowany `ProviderResponse`,
- nie oznacza automatycznie konca calego requestu HTTP.

To oznacza, ze jeden request moze zawierac wiecej niz jedno `done`.
Przyklad:

- pierwsze `done` po odpowiedzi modelu, ktora konczy sie `tool_calls`,
- drugie `done` po finalnej odpowiedzi tekstowej po wykonaniu narzedzia.

### 5. Frontend nie musi renderowac wszystkich delt

Backend moze wysylac granularne eventy, a frontend moze wybrac jak je pokazac.

Przykladowo:

- `text_delta` mozna renderowac na zywo,
- `function_call_delta` mozna ignorowac w UI,
- `function_call_done` mozna pokazac jako pelny "tool loading" lub "tool invoked",
- `done` mozna traktowac jako granice jednej odpowiedzi modelu.

To znaczy, ze granularny kontrakt SSE nie wymusza "token po tokenie" dla kazdego typu danych.

## Docelowy kontrakt streamingu

### Eventy SSE

Pierwsza wersja powinna wspierac nastepujace eventy:

- `text_delta`
- `text_done`
- `function_call_delta`
- `function_call_done`
- `done`
- `error`

Minimalny kontrakt typow po stronie providera:

```python
ProviderStreamEvent =
    | {"type": "text_delta", "delta": str}
    | {"type": "text_done", "text": str}
    | {"type": "function_call_delta", "call_id": str, "name": str, "arguments_delta": str}
    | {"type": "function_call_done", "call_id": str, "name": str, "arguments": dict[str, Any]}
    | {"type": "done", "response": ProviderResponse}
    | {"type": "error", "error": str, "code": str | None}
```

Nazewnictwo w Pythonie powinno zostac dopasowane do stylu projektu, ale wartosci `type` w payloadzie SSE powinny pozostac stabilne.

### Semantyka eventow

`text_delta`

- kolejny fragment tekstu z aktualnie generowanej odpowiedzi.

`text_done`

- zamkniecie biezacego tekstu,
- payload zawiera pelny tekst wygenerowany w tej czesci odpowiedzi.

`function_call_delta`

- kolejny fragment argumentow function calla,
- payload niesie surowy string fragmentu JSON.

`function_call_done`

- finalna wersja function calla,
- payload zawiera sparsowane argumenty jako slownik.

`done`

- finalny, ujednolicony `ProviderResponse`,
- punkt graniczny jednej odpowiedzi modelu,
- event potrzebny runnerowi do dalszego zapisu itemow i wykonywania tooli.

`error`

- blad po stronie providera lub stream parsera,
- powinien konczyc dalsza emisje eventow dla danej odpowiedzi.

## Docelowy kontrakt HTTP

### Wejscie

Obecny `ChatRequest` moze zostac bez zmiany kontraktu:

- `stream: bool = False`

### Wyjscie dla `stream=False`

Bez zmian:

- zwykly `ChatResponse` jako JSON.

### Wyjscie dla `stream=True`

Endpoint zwraca `StreamingResponse` z naglowkami:

- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `Connection: keep-alive`

Kazdy event ma byc serializowany jako:

```text
event: <type>
data: <json>

```

Nie planujemy dodatkowego opakowania typu `{"data": ..., "error": ...}`.
Payload SSE powinien byc bezposrednio JSON-em pojedynczego eventu.

## Docelowa architektura przeplywu

### 1. HTTP

`api.py`:

- rozpoznaje `payload.stream`,
- dla `False` uzywa obecnej sciezki JSON,
- dla `True` uruchamia generator SSE oparty o `chat_service.stream_prepared_chat(...)`.

### 2. Chat service

`chat_service.py`:

- `prepare_chat(...)` przestaje odrzucac `stream=True`,
- `process_chat(...)` pozostaje dla trybu non-stream,
- dochodzi `stream_prepared_chat(...)`,
- opcjonalnie dochodzi `process_chat_stream(...)` dla spojnosci z TS referencja.

### 3. Runner

`runner.py`:

- obecna sciezka `run_agent(...)` zostaje,
- dochodzi `execute_turn_stream(...)`,
- dochodzi `run_agent_stream(...)`,
- obie sciezki korzystaja ze wspolnego `handle_turn_response(...)`.

### 4. Provider

`base.py` i `types.py`:

- kontrakt providera dostaje metode `stream(...)`,
- `types.py` definiuje `ProviderStreamEvent`.

`openrouter_provider.py`:

- wykonuje request streamujacy,
- parsuje SSE providera,
- akumuluje stan odpowiedzi,
- emituje wspolne eventy,
- na koncu emituje `done` z finalnym `ProviderResponse`.

## Plan implementacji

### 1. Rozszerzyc kontrakt providerow

Pliki:

- `src/app/providers/types.py`
- `src/app/providers/base.py`
- `src/app/providers/__init__.py`

Zakres:

- dodac typy eventow strumieniowych,
- ewentualnie wzbogacic `ProviderResponse`, jesli bedzie potrzebne np. `id`, `model`, `finish_reason`,
- dodac `async def stream(...) -> AsyncIterable[ProviderStreamEvent]`,
- wyeksportowac nowe typy z `__init__.py`.

Wazna decyzja:

- nie przeciagac do pierwszej wersji `reasoning_delta` ani innych eventow, ktorych frontend jeszcze nie potrzebuje.

### 2. Dolozyc streaming do OpenRouter providera

Plik:

- `src/app/providers/openrouter_provider.py`

Zakres:

- wysylac request z `stream=true`,
- zaimplementowac parser SSE odpowiedzi HTTP,
- budowac lokalny `StreamState` podobny do wzorca z `4th-devs`,
- akumulowac tekst i function calle,
- emitowac:
  - `text_delta`,
  - `text_done`,
  - `function_call_delta`,
  - `function_call_done`,
  - `done`,
  - `error`.

Rekomendacja techniczna:

- nie mieszac parsera SSE z mapowaniem outputu do itemow,
- wydzielic pomocnicze funkcje:
  - do parsowania linii SSE,
  - do akumulacji stanu,
  - do budowy finalnego `ProviderResponse`.

### 3. Rozbudowac runner o sciezke stream

Plik:

- `src/app/runtime/runner.py`

Zakres:

- dodac `execute_turn_stream(...)`,
- dodac `run_agent_stream(...)`,
- stream ma wypychac eventy providera na biezaco,
- runner czeka na `done`, zeby dostac finalny `ProviderResponse`,
- po `done` wywoluje te sama logike `handle_turn_response(...)`,
- po bledzie streamingu zwraca `error` i konczy wykonanie.

Kluczowa zasada:

- nie duplikowac logiki `store_provider_output(...)`, `store_tool_output(...)` ani `handle_turn_response(...)`.

### 4. Rozszerzyc chat service

Plik:

- `src/app/services/chat_service.py`

Zakres:

- usunac blokade `stream=True` z `prepare_chat(...)`,
- zostawic obecne `process_chat(...)` i `execute_chat(...)`,
- dodac `stream_prepared_chat(...)`,
- opcjonalnie dodac `process_chat_stream(...)`, ktore zrobi:
  - `prepare_chat(...)`,
  - potem `yield from stream_prepared_chat(...)`.

W przypadku bledu `prepare_chat(...)` dla streamu rekomendacja jest taka sama jak w referencji TS:

- zwrocic pojedynczy event `error`,
- nie zmieniac tego na zwykly JSON response.

### 5. Dodac adapter SSE w FastAPI

Plik:

- `src/app/api/v1/chat/api.py`

Zakres:

- dla `stream=False` zachowac obecne zachowanie,
- dla `stream=True` zwracac `StreamingResponse`,
- dodac lokalny helper serializujacy event do formatu SSE,
- zamykac `chat_service` po zakonczonym generatorze.

Rekomendacja:

- nie budowac tutaj logiki runtime,
- route ma tylko spinac HTTP z `ChatService`.

### 6. Dookreslic semantyke `done`

Ta decyzja musi byc zapisana w kodzie i testach:

- `done` jest emitowany zawsze po zakonczonej odpowiedzi providera,
- `done` niesie pelny `ProviderResponse`,
- jeden request HTTP moze zawierac wiele eventow `done`,
- po `done` runner moze:
  - zakonczyc agenta,
  - wykonac narzedzia,
  - wejsc w kolejna ture i emitowac kolejne eventy.

To zachowanie ma byc jawne w dokumentacji endpointu.

### 7. Testy kontraktu provider stream

Pliki:

- nowy test providera, np. `src/tests/test_openrouter_provider_stream.py`

Zakres:

- parsowanie prostego tekstu,
- parsowanie odpowiedzi z function callem,
- poprawna kolejnosc `delta -> done`,
- poprawna budowa finalnego `ProviderResponse`,
- mapowanie bledow do eventu `error`.

### 8. Testy runner stream

Pliki:

- rozszerzenie `src/tests/test_runner_events.py`
- albo nowy plik typu `src/tests/test_runner_stream.py`

Zakres:

- happy path tekstowy,
- tool call + kolejna tura,
- propagacja bledu streamingu,
- finalne zapisanie itemow po `done`,
- brak duplikacji itemow wzgledem trybu non-stream.

### 9. Testy API SSE

Pliki:

- nowy test endpointu chat, np. `src/tests/test_chat_stream_api.py`

Zakres:

- `stream=true` zwraca `text/event-stream`,
- poprawny format `event:` i `data:`,
- blad setupu zwraca event `error`,
- po zakonczonym streamie service i sesja sa poprawnie zamkniete.

### 10. Rollout etapowy

Rekomendowana kolejnosc wdrozenia:

1. typy streamingu i kontrakt providera,
2. streaming w `OpenRouterProvider`,
3. `Runner.execute_turn_stream(...)`,
4. `Runner.run_agent_stream(...)`,
5. `ChatService.stream_prepared_chat(...)`,
6. FastAPI `StreamingResponse`,
7. testy end-to-end dla `stream=true`.

Taka kolejnosc daje mozliwosc testowania od dolu i nie miesza od razu problemow providera, runnera i HTTP.

## Decyzje produktowe dla frontendu

Backend powinien wysylac pelny zestaw eventow, ale frontend moze wybrac jak je renderowac.

Rekomendowane zalozenie dla pierwszej wersji UI:

- renderowac `text_delta`,
- ignorowac `function_call_delta`,
- reagowac na `function_call_done` jako stan "tool in progress",
- traktowac `done` jako granice jednej odpowiedzi modelu,
- traktowac `error` jako finalny blad streamu.

To pozwala zachowac bogaty kontrakt backendowy bez wymuszania zbyt gadatliwego UI.

## Ryzyka i uwagi

### 1. Streaming bez background jobs nadal trzyma request otwarty

To jest akceptowalne dla tego etapu.
SSE nie rozwiazuje background execution i nie ma tego rozwiazywac.

### 2. Parser SSE musi byc odporny na niepelne eventy

Najbardziej wrazliwa czesc implementacji to parser po stronie providera.
Warto od razu wydzielic i przetestowac go osobno.

### 3. `done` jest krytyczny dla spojnosci runnera

Bez `done` runner nie ma pewnego punktu przejscia z trybu strumieniowego do zapisu itemow i wykonywania tooli.

### 4. Nie nalezy przerzucac odpowiedzialnosci UI do backendu

Backend ma emitowac poprawny kontrakt eventow.
To frontend decyduje, czy chce pokazac delty, pelny tool call czy tylko finalny stan.

## Kryteria zakonczonego etapu

Etap uznajemy za zakonczony, gdy:

- `POST /api/chat/completions` obsluguje `stream=true`,
- endpoint zwraca prawidlowe SSE,
- OpenRouter provider implementuje `stream(...)`,
- runner potrafi streamowac i dalej wykonywac tools,
- event `done` jest zaimplementowany i przetestowany,
- sciezka non-stream pozostaje bez regresji,
- `EventBus` nie jest elementem krytycznej sciezki SSE.
