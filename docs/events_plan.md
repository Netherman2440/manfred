# Plan implementacji eventow, loggera i Langfuse

Ten dokument rozpisuje plan wdrozenia warstwy observability dla `manfreda`.
Zakres obejmuje:

- system eventow runtime,
- globalny logger eventowy,
- subscriber Langfuse,
- punkty integracji z `Runner`,
- testy i kolejnosc rolloutu.

Plan celowo traktuje eventy jako warstwe obserwowalnosci, a nie jako mechanizm sterowania petla agenta.

## Referencje

- Event bus: [`src/app/events/event_bus.py`](../src/app/events/event_bus.py)
- Definicja bazowa eventu: [`src/app/events/definitions/base.py`](../src/app/events/definitions/base.py)
- Przyklad eventu: [`src/app/events/definitions/agent_started.py`](../src/app/events/definitions/agent_started.py)
- Runner: [`src/app/runtime/runner.py`](../src/app/runtime/runner.py)
- DI container: [`src/app/container.py`](../src/app/container.py)
- App bootstrap: [`src/app/main.py`](../src/app/main.py)
- Konfiguracja: [`src/app/config.py`](../src/app/config.py)
- Referencja TS emitter: zewnetrzny plik `4th-devs/01_05_agent/src/events/emitter.ts` (brak kopii w tym repo)
- Referencja TS logger: zewnetrzny plik `4th-devs/01_05_agent/src/lib/event-logger.ts` (brak kopii w tym repo)
- Referencja TS Langfuse subscriber: zewnetrzny plik `4th-devs/01_05_agent/src/lib/langfuse-subscriber.ts` (brak kopii w tym repo)
- Referencja TS event types: zewnetrzny plik `4th-devs/01_05_agent/src/events/types.ts` (brak kopii w tym repo)

## Cel etapu

Na koniec tego etapu `manfred` ma umiec:

- emitowac eventy z lifecycle runnera,
- budowac wspolny kontekst korelacyjny dla wszystkich eventow,
- logowac wszystkie eventy przez globalnego subscriber-a,
- wysylac wybrane eventy do Langfuse,
- izolowac runtime od awarii listenerow,
- utrzymac eventy jako mechanizm observability, a nie sterowania flow.

## Zasady architektoniczne

### 1. Eventy nie steruja runtime

Zmiana statusu agenta, przejscie miedzy turami i wykonanie tooli maja pozostac w `Runner`.
Event ma byc emitowany dopiero po wykonaniu kroku albo przy wejsciu w krok, ale nigdy nie ma decydowac o tym, co runner robi dalej.

### 2. Payload eventu ma byc samowystarczalny

Subscriber nie powinien doczytywac repozytoriow, zeby zrozumiec event.
Wspolny kontekst i payload konkretnego eventu maja wystarczyc do:

- logowania,
- tracingu,
- prostego debugowania,
- korelacji eventow miedzy turnami.

### 3. Listener nie moze przerwac wykonania agenta

`EventBus` ma wywolywac handlery w trybie `safe_call`.
Jesli logger albo Langfuse subscriber rzuci wyjatek, blad ma zostac zalogowany, ale runner ma kontynuowac wykonanie.

### 4. Event bus jest dependency wspoldzielona

`EventBus` powinien byc rejestrowany w `container.py` i wstrzykiwany do runtime.
Nie nalezy tworzyc nowego busa ad hoc w route handlerach ani wewnatrz `Runner`.

## Stan obecny w `manfred`

Aktualny stan kodu wymusza kilka zalozen dla planu:

- `src/app/events/event_bus.py` jest pusty,
- `src/app/events/definitions/base.py` jest pusty,
- `src/app/events/definitions/agent_started.py` jest pusty,
- `Runner` jest juz zaimplementowany i to on jest realnym miejscem emisji eventow,
- `LANGFUSE_*` istnieje juz w `config.py`,
- repo nie ma jeszcze gotowej infrastruktury logowania runtime,
- `AgentStatus.WAITING` istnieje, ale flow `waiting/resumed` nie jest jeszcze zaimplementowane,
- `run_agent(...)` zwraca dzis blad dla agenta w stanie `WAITING`.

Wniosek praktyczny:

- eventy `agent.started`, `turn.started`, `generation.completed`, `tool.called`, `tool.completed`, `tool.failed`, `turn.completed`, `agent.completed`, `agent.failed` da sie wdrozyc od razu,
- eventy `agent.waiting`, `agent.resumed`, `agent.cancelled` warto zaprojektowac juz teraz, ale pelne emitowanie powinno wejsc razem z przyszlym flow async/human tools.

## Docelowy kontrakt eventow

Zakres wynikajacy z grafiki i use-case'ow:

- `agent.started`
- `turn.started`
- `tool.called`
- `tool.completed`
- `turn.completed`
- `agent.waiting`
- `agent.resumed`
- `agent.completed`
- `agent.failed`
- `agent.cancelled`

Dodatkowo rekomendowane od razu:

- `tool.failed`
- `generation.completed`

Powod:

- bez `tool.failed` observability bledow tooli bedzie niepelna,
- bez `generation.completed` Langfuse nie pokaże sensownie wywolan modelu.

## Wspolny kontekst eventu

W `base.py` warto wprowadzic wspolna strukture typu `EventContext`.
Minimalny zestaw pol:

- `event_id`
- `timestamp`
- `trace_id`
- `session_id`
- `agent_id`
- `root_agent_id`
- `parent_agent_id`
- `depth`

Rekomendacja:

- `trace_id` powinno byc stabilne dla calego runa,
- `timestamp` trzymac jako `datetime` albo unix epoch, ale konsekwentnie w calym systemie,
- `parent_agent_id` zostawic opcjonalne,
- nie mieszac tu payloadu eventu specyficznego dla narzedzia czy LLM.

## Struktura plikow

Rekomendowany uklad:

- `src/app/events/event_bus.py`
- `src/app/events/definitions/base.py`
- `src/app/events/definitions/agent_started.py`
- `src/app/events/definitions/turn_started.py`
- `src/app/events/definitions/turn_completed.py`
- `src/app/events/definitions/generation_completed.py`
- `src/app/events/definitions/tool_called.py`
- `src/app/events/definitions/tool_completed.py`
- `src/app/events/definitions/tool_failed.py`
- `src/app/events/definitions/agent_completed.py`
- `src/app/events/definitions/agent_failed.py`
- `src/app/events/definitions/agent_waiting.py`
- `src/app/events/definitions/agent_resumed.py`
- `src/app/events/definitions/agent_cancelled.py`

Kazdy event w osobnym pliku jest zgodny z kierunkiem, ktory juz zaznaczyles.

## Plan implementacji

### 1. Zdefiniowac baze eventow

W `base.py` warto zrobic:

- `EventContext`,
- `BaseEvent`,
- alias lub union dla wspolnego typu eventu,
- helper do tworzenia kontekstu na podstawie `Agent`.

Jesli projekt ma zostac przy dataclasses, to eventy tez warto utrzymac jako `@dataclass(slots=True, frozen=True)`.
To bedzie spójne z reszta domeny i nie wymusi Pydantica w runtime.

### 2. Zaimplementowac `EventBus`

W `event_bus.py` potrzebny jest prosty in-memory bus:

- `emit(event)`,
- `subscribe(event_type, handler) -> unsubscribe`.

Kontrakt `subscribe(...)` powinien obslugiwac dwa tryby:

- `subscribe("agent.started", handler)` dla konkretnego typu eventu,
- `subscribe("any", handler)` dla globalnego subscriber-a.

Zachowanie:

- najpierw handlery konkretnego typu, potem `any`, albo odwrotnie, byle konsekwentnie,
- kazdy handler opakowany w `safe_call`,
- bus nie robi sterowania stanem i nie dotyka repozytoriow.

### 3. Zbudowac fabryke kontekstu eventow

`Runner` nie powinien skladac `ctx` recznie w kazdym miejscu.
Warto dodac helper, np.:

- `build_event_context(agent: Agent, trace_id: str) -> EventContext`

Mozliwe miejsce:

- `src/app/events/definitions/base.py`, jesli ma zostac blisko typow,
- albo osobny modul pomocniczy w `src/app/events/`.

### 4. Ustalic zrodlo `trace_id`

To jest jedna z wazniejszych decyzji.
Ustalona decyzja na start:

- generowac `trace_id` przy `run_agent(...)`,
- trzymac je w `AgentRunContext`,
- pozniej, gdy wejdzie `waiting/resumed`, rozważyć zapisanie `trace_id` w modelu agenta lub sesji.

Nie polecam uzalezniac Langfuse od ephemeral ID, jesli docelowo ma byc resume i dostarczanie wynikow po czasie.

### 5. Wstrzyknac `EventBus` do runtime

Zmiany w `container.py`:

- zarejestrowac singleton `EventBus`,
- zarejestrowac `Runner` w kontenerze,
- przekazac `EventBus` do `Runner`,
- udostepnic go aplikacji przy starcie.

Zmiany w `ChatService`:

- repozytoria nie powinny byc tworzone ad hoc wewnatrz serwisu,
- `Runner` nie powinien byc tworzony wewnatrz serwisu,
- `ChatService` powinien dostawac repozytoria i `Runner` przez DI z `container.py`.

To jest zgodne z konwencja repo: `container.py` pozostaje pojedynczym miejscem skladania zaleznosci wspoldzielonych.

### 6. Podpiac eventy w `Runner`

Punkty emisji w `runner.py` powinny odpowiadac realnym krokom runtime.

#### `agent.started`

Emitowac po:

- zaladowaniu kontekstu,
- ustawieniu `agent.status = RUNNING`,
- zapisie agenta do repo.

Payload:

- `model`,
- `task`,
- opcjonalnie `user_id`,
- opcjonalnie `user_input`,
- opcjonalnie `agent_name`.

#### `turn.started`

Emitowac na poczatku kazdej iteracji petli turna.

Payload:

- `turn_count`

Ustalona semantyka:

- `turn_count` w eventach ma odzwierciedlac `agent.turn_count`,
- nie wprowadzac osobnej numeracji tylko dla observability,
- opisac jawnie, ze jest to licznik zgodny z polem domenowym agenta.

#### `generation.completed`

Emitowac po `provider.generate(...)`.

Payload:

- `model`
- `instructions`
- `input`
- `output`
- `usage`
- `duration_ms`
- `start_time`

Ten event powinien byc samowystarczalny, nawet jesli Langfuse bedzie jedynym subscriberem, ktory go uzywa.

#### `tool.called`

Emitowac tuz przed `tool_registry.execute(...)`.

Payload:

- `call_id`
- `name`
- `arguments`

#### `tool.completed`

Emitowac po wykonaniu toola, kiedy wynik jest znany i ma zostac zapisany jako `FUNCTION_CALL_OUTPUT`.

Payload:

- `call_id`
- `name`
- `arguments`
- `output`
- `duration_ms`
- `start_time`

#### `tool.failed`

Emitowac, gdy:

- tool rzuci wyjatek,
- albo zwroci rezultat `ok=False`.

Przyjeta decyzja:

- emitowac `tool.failed` rowniez wtedy, gdy tool nie zostal znaleziony.

Payload:

- `call_id`
- `name`
- `arguments`
- `error`
- `duration_ms`
- `start_time`

#### `turn.completed`

Emitowac po zakonczeniu obslugi wszystkich function calli w danej turze.

Payload:

- `turn_count`
- `usage`

Na starcie mozna podac usage tylko z aktualnego response providera.
Pozniej mozna rozważyć osobna agregacje usage na poziomie agenta.

#### `agent.completed`

Emitowac przed zwrotem sukcesu z `run_agent(...)`.

Payload:

- `duration_ms`
- `usage`
- `result`

#### `agent.failed`

Emitowac w kazdej sciezce blednej konczacej run:

- nieznany provider,
- blad providera,
- przekroczony `max_turns`,
- nieobslugiwany typ toola,
- inne bledy wykonania.

Payload:

- `error`

#### `agent.waiting`, `agent.resumed`, `agent.cancelled`

Te eventy warto miec zdefiniowane juz teraz, ale emisje wdrozyc dopiero z rzeczywistym flow:

- `WAITING` dla async/human tools,
- `resume` po dostarczeniu zewnetrznego wyniku,
- `cancelled` po realnym mechanizmie anulowania.

Dzis `Runner` nie ma jeszcze tej semantyki, wiec nie nalezy udawac implementacji samym eventem.

### 7. Dodac event logger

Rekomendowany nowy modul:

- `src/app/observability/event_logger.py`

Zadanie loggera:

- subskrybowac wszystkie eventy przez `subscribe("any", ...)`,
- logowac je w sposob strukturalny,
- nie dotykac stanu runtime.

Minimalna zawartosc logu:

- `event_type`,
- `trace_id`,
- `session_id`,
- `agent_id`,
- `depth`,
- payload eventu.

Wazne:

- logger ma byc globalnym subscriberem bootstrapped przy starcie appki,
- nie nalezy logowac przez `print`,
- jesli w repo nie ma jeszcze wspolnego logger setup, trzeba go dolozyc jako osobny maly krok.

### 8. Dodac subscriber Langfuse

Rekomendowany nowy modul:

- `src/app/observability/langfuse_subscriber.py`

Subscriber powinien sluchac tylko eventow potrzebnych do tracingu:

- `agent.started`
- `agent.completed`
- `agent.failed`
- `agent.cancelled`
- `agent.waiting`
- `generation.completed`
- `tool.completed`
- `tool.failed`

Zakres odpowiedzialnosci:

- tworzenie trace/span dla root agenta,
- utrzymywanie mapy aktywnych obserwacji per `agent_id`,
- budowanie hierarchii parent/child po `parent_agent_id`,
- domykanie obserwacji na `completed`, `failed`, `cancelled`, `waiting`.

Zachowanie operacyjne:

- jesli `LANGFUSE_ENABLED` jest `False`, subscriber jest no-op,
- jesli brakuje kluczy, subscriber jest no-op,
- bledy po stronie SDK nie moga przerwac runnera.

Decyzja projektowa:

- Langfuse wchodzi w zakres planu i kontraktu architektonicznego juz teraz,
- implementacja Langfuse moze byc wykonana osobno niz event bus i logger,
- plan powinien zostac rozpisany tak, zeby wdrozenie Langfuse bylo niezalezne od szczegolow implementacji eventow.

### 9. Uzupełnic konfiguracje i zaleznosci

W `config.py` pola Langfuse juz istnieja:

- `LANGFUSE_ENABLED`
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_HOST`
- `LANGFUSE_ENVIRONMENT`

Brakujace kroki:

- dodac odpowiedni SDK do `src/pyproject.toml`,
- jesli projekt tego wymaga, dodac parametry typu flush timeout,
- dodac `.env.EXAMPLE`, bo repo go obecnie nie ma, a konwencja projektu tego wymaga.

### 10. Zarejestrowac subscribery przy starcie aplikacji

W `main.py` warto dodac startup lub `lifespan`, ktory:

- pobiera `EventBus` z containera,
- podpina `EventLogger`,
- warunkowo podpina `LangfuseSubscriber`,
- na shutdown wykonuje cleanup i flush.

To powinien byc punkt centralny dla globalnych subscriberow runtime.

### 11. Dolozyc testy

Minimalny zestaw testow:

- `EventBus` wywoluje subskrybenta po typie eventu,
- `EventBus` wywoluje `subscribe_any(...)`,
- wyjatek listenera nie rozwala `emit(...)`,
- `Runner` emituje eventy w poprawnej kolejnosci dla happy path,
- `Runner` emituje `tool.failed` i `agent.failed` dla sciezki bledu,
- Langfuse subscriber bez credentiali zachowuje sie jak no-op.

Jesli nie ma jeszcze infrastruktury testowej, ten etap trzeba doliczyc do prac.

## Proponowany rollout

### Etap A - eventy gotowe od razu

Najmniejszy sensowny zakres:

- `agent.started`
- `turn.started`
- `generation.completed`
- `tool.called`
- `tool.completed`
- `tool.failed`
- `turn.completed`
- `agent.completed`
- `agent.failed`
- `EventBus`
- globalny event logger

To da od razu realna obserwowalnosc bez czekania na async tools.

### Etap B - Langfuse

Po stabilizacji eventow runtime:

- subscriber Langfuse,
- startup/shutdown wiring,
- flush i cleanup,
- testy integracyjne lub smoke testy.

Ustalony kierunek:

- Langfuse pozostaje w planie i w przewidywanym rollout-cie,
- ale moze byc realizowany przez osobny task lub osobna osobe po ustabilizowaniu kontraktu eventow.

### Etap C - waiting/resumed/cancelled

Dopiero gdy wejdzie prawdziwy flow:

- async tools,
- human tools,
- `deliver`,
- ewentualne child agenty,

mozna domknac:

- `agent.waiting`
- `agent.resumed`
- `agent.cancelled`

## Najwazniejsze decyzje do zamrozenia

Przed implementacja warto jawnie przyjac:

- eventy sa observability only,
- `generation.completed` wchodzi od razu mimo ze nie ma go na grafice,
- `tool.failed` wchodzi od razu,
- `tool.failed` obejmuje tez przypadek `tool not found`,
- `trace_id` ma byc stabilne per run, a docelowo per wznowione wykonanie,
- `trace_id` jest trzymane w `AgentRunContext`,
- `Runner` i repozytoria sa skladane przez DI w `container.py`,
- globalny subscriber korzysta z `subscribe("any", handler)`,
- `turn_count` w eventach ma byc zgodny z `agent.turn_count`,
- `waiting/resumed` sa w kontrakcie, ale nie sa fake-implementowane bez realnego flow.

## Proponowana kolejnosc prac

1. Zdefiniowac `EventContext` i wszystkie klasy eventow.
2. Zaimplementowac `EventBus`.
3. Wstrzyknac `EventBus` do runtime przez `container.py`.
4. Podpiac emisje eventow w `Runner`.
5. Dodac globalny event logger.
6. Zarejestrowac subscribery przy starcie appki.
7. Dodac Langfuse subscriber.
8. Dolozyc testy.
9. Rozszerzyc kontrakt o `waiting/resumed/cancelled` razem z przyszlym flow async tools.

## Podsumowanie

Najwlasciwsza implementacja dla obecnego stanu `manfreda` to:

- in-memory `EventBus`,
- eventy emitowane z `Runner`,
- logger subskrybujacy wszystko,
- Langfuse subskrybujacy tylko wybrane eventy,
- brak sterowania runtime przez eventy,
- rollout podzielony na czesc gotowa od razu i czesc zalezna od `waiting/resumed`.

To zachowuje kierunek z `4th-devs`, ale jest dopasowane do tego, ze `manfred` ma juz dzis prostszy runtime i nie ma jeszcze pelnego flow deferred execution.
