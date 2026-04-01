# Plan implementacji `chat_service.py`

Ten dokument rozpisuje etap 1 migracji przykładu `4th-devs/01_05_agent` do `manfreda`.
Zakres tego etapu obejmuje wyłącznie warstwę API i `chat_service`.
Plan runnera, providera i tur agenta jest opisany osobno w `docs/runner_plan.md`.

## Referencje

- TS service: `/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.service.ts`
- TS turn setup: `/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.turn.ts`
- TS schema: `/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.schema.ts`
- Docelowy plik: `/home/netherman/code/manfred/src/app/services/chat_service.py`
- Przyszly runner: `/home/netherman/code/manfred/src/app/runtime/runner.py`

## Cel etapu

Na koniec tego etapu `manfred` ma umiec:

- przyjac uproszczony request `POST /chat/completions`,
- zbudowac `ChatService` z glowna metoda `process_chat(chat_request)`,
- rozdzielic flow na `prepare_chat(...)` i `execute_chat(...)`,
- zaladowac lub utworzyc sesje,
- rozwiazac konfiguracje agenta z override'ow requestu lub runtime root agenta,
- policzyc `last_sequence` przed aktualna tura,
- zapisac wszystkie `input items`,
- wywolac placeholder dla runnera,
- zwrocic odpowiedz z itemami widocznymi dla uzytkownika z aktualnej tury.

Ten etap nie implementuje jeszcze faktycznej petli runnera, providera ani obslugi tool execution.

## Docelowy kontrakt requestu

`ChatRequest` w `manfredzie` powinien byc prostszy niz w TypeScripcie i miec taka postac:

```python
class ChatRequest(BaseModel):
    input: list[ChatInputItem] = Field(default_factory=list)
    session_id: str | None = None
    stream: bool = False
    agent_config: ChatAgentConfigInput | None = None
```

`ChatAgentConfigInput`:

- `model: str | None = None`
- `task: str | None = None`
- `tools: list[ToolDefinition] | None = None`
- `temperature: float | None = None`

Kazde pole w `agent_config` jest opcjonalne.
Jesli request nie podaje wartosci, serwis uzupelnia je z bazowego root agenta budowanego w runtime.

### Proponowany minimalny model `input`

Zeby nie komplikowac etapu 1, wejscie warto ograniczyc do jednego wariantu:

- `message`

To daje najprostszy kontrakt pod start i nie wypycha jeszcze logiki runnera do API.

Przykladowy kierunek:

```python
class MessageInputItem(BaseModel):
    type: Literal["message"] = "message"
    role: Literal["user", "assistant", "system"]
    content: str
```

Na etapie 1 mozna celowo nie wspierac jeszcze zlozonego contentu multimodalnego.

## Docelowy kontrakt serwisu

W `/home/netherman/code/manfred/src/app/services/chat_service.py` powinna powstac klasa `ChatService` z trzema metodami publicznymi:

```python
class ChatService:
    async def process_chat(self, chat_request: ChatRequest) -> ChatResponse: ...
    async def prepare_chat(self, chat_request: ChatRequest) -> PreparedChatSetupResult: ...
    async def execute_chat(self, agent_id: str, last_sequence: int) -> ChatResponse: ...
```

`process_chat(chat_request)` robi tylko dwa kroki:

```python
setup = await self.prepare_chat(chat_request)
if not setup.ok:
    return ...

return await self.execute_chat(setup.agent.id, setup.last_sequence)
```

## Plan implementacji

### 1. Uporzadkowac kontrakt API

Pliki:

- `/home/netherman/code/manfred/src/app/api/v1/chat/schema.py`
- `/home/netherman/code/manfred/src/app/api/v1/chat/api.py`

Zakres:

- zastapic obecne `message: str` nowym `ChatRequest`,
- dodac `ChatResponse` zgodny z etapem 1,
- poprawic sciezke endpointu z `/chat/competions` na `/chat/completions`,
- podlaczyc `ChatService` przez DI,
- jesli `stream=True`, na razie zwracac jawny blad `not implemented` albo `501`, bo streaming nalezy do etapu runnera.

### 2. Zdefiniowac modele pomocnicze dla etapu 1

W `chat_service.py` albo w dedykowanym module obok serwisu powinny pojawic sie:

- `ChatAgentConfigInput`
- `ResolvedAgentConfig`
- `PreparedChatSetup`
- `PreparedChatSetupResult`

Wazne rozroznienie:

- `ChatAgentConfigInput` ma pola opcjonalne, bo pochodzi z requestu,
- `ResolvedAgentConfig` ma pola uzupelnione, bo jest gotowy do stworzenia lub odswiezenia agenta.

### 3. Wprowadzic runtime root agent config

Uzytkownik chce na razie tworzyc bazowego root agenta w runtime, a nie ladowac go z pliku.
Plan dla etapu 1:

- dodac prosty helper zwracajacy domyslny `AgentConfig`,
- trzymac go blisko `ChatService` albo w module runtime config,
- ustawic tam bazowy `model`, `task`, `tools`, `temperature`,
- merge robic w kolejnosci:
  - runtime root agent config
  - `request.agent_config`

Efekt ma byc deterministyczny: request nadpisuje tylko te pola, ktore podal.

### 4. Zaimplementowac `load_session`

`prepare_chat` powinno najpierw rozwiazac sesje:

- gdy `session_id` jest puste, tworzymy nowa sesje,
- gdy `session_id` istnieje i sesja jest znaleziona, uzywamy jej,
- gdy `session_id` istnieje, ale sesja nie istnieje, decyzje trzeba zamrozic juz teraz.

Rekomendacja dla etapu 1:

- jesli klient poda nieistniejace `session_id`, zwracac blad walidacyjny biznesowy zamiast tworzyc nowa sesje po cichu.

To jest bezpieczniejsze od zachowania z referencji TS i zmniejsza ryzyko trudnych do wykrycia bugow po stronie klienta.

### 5. Zaimplementowac `load_agent_config`

`prepare_chat` powinno rozwiazac pelna konfiguracje agenta:

- pobrac runtime root agent config,
- nalozyc na niego override z `chat_request.agent_config`,
- upewnic sie, ze finalnie zawsze mamy `model`, `task`, `tools`, `temperature`.

Na tym etapie nie ma jeszcze loadera agentow z pliku, wiec wszystko dzieje sie in-memory.

### 6. Rozwiazac root agenta sesji

Po zaladowaniu sesji i konfiguracji serwis powinien:

- sprobowac odczytac `session.root_agent_id`,
- jesli istnieje, zaladowac tego agenta,
- jesli nie istnieje, utworzyc nowego root agenta dla sesji,
- jesli sesja ma `root_agent_id`, ale agent nie istnieje, potraktowac to jako blad integralnosci.

Istotny detal techniczny:

- `AgentModel.root_agent_id` jest obecnie `nullable=False`,
- tak ma zostac,
- root agent powinien byc tworzony od razu z `root_agent_id = agent.id`.

To powinno byc wymuszone w fabryce agenta albo repozytorium tworzacym root agenta.

### 7. Wyznaczyc `last_sequence`

`prepare_chat` powinno pobrac sequence ostatniego itemu przypisanego do agenta przed zapisem nowego inputu.

Semantyka:

- to jest granica odpowiedzi dla aktualnej tury,
- `execute_chat` bedzie zwracac tylko itemy z `sequence > last_sequence`,
- dzieki temu odfiltrujemy stare itemy i user input z tej samej tury.

Rekomendacja implementacyjna:

- dodac do `ItemRepository` helper typu `get_last_sequence(agent_id) -> int`,
- nie bazowac na wczytywaniu calej listy itemow, jesli mozna to policzyc query.

### 8. Tworzyc itemy dla wszystkich `input items`

`prepare_chat` ma zapisac kazdy element z `chat_request.input` jako item domenowy tej sesji i tego agenta.

Zakres etapu 1:

- `message` zapisujemy jako `ItemType.MESSAGE`,
- nadajemy `role` zgodnie z requestem,
- zachowujemy sequence rosnace w obrebie agenta.

### 9. Zwracac `PreparedChatSetup`

Jesli `prepare_chat` zakonczy sie sukcesem, powinien zwrocic strukture podobna do:

```python
@dataclass(slots=True)
class PreparedChatSetup:
    session: Session
    agent: Agent
    last_sequence: int
```

Jesli przygotowanie sie nie uda, serwis powinien zwrocic rezultat typu `ok=False` z czytelnym bledem domenowym.

### 10. Zaimplementowac `execute_chat`

`execute_chat(agent_id, last_sequence)` w etapie 1 ma:

- przygotowac miejsce na `runner.run_agent(...)`,
- wywolac placeholder runnera lub tymczasowa metode stub,
- pobrac itemy agenta po wykonaniu,
- odfiltrowac tylko itemy widoczne dla uzytkownika.

Widoczne itemy dla odpowiedzi z tej tury:

- wiadomosci `assistant`,
- `function_call`,
- opcjonalnie `function_call_output` dopiero wtedy, gdy bedzie to potrzebne przez finalny kontrakt API.

Na teraz, zgodnie z Twoim zalozeniem, priorytetem jest zwracanie itemow od assistanta i tool calli, bez user message z biezacej tury.

### 11. Przygotowac response mapper

W etapie 1 warto miec prosty mapper odpowiedzi, zamiast mieszac formatowanie w serwisie.

Minimalny kierunek:

- `session_id`
- `agent_id`
- `status`
- `items`

To wystarczy do dalszego podpiecia runnera w etapie 2 bez kolejnego przebudowywania endpointu.

### 12. Spiac transakcje i commit

`prepare_chat` zapisuje sesje, agenta i itemy, wiec trzeba jasno ustalic granice transakcji.

Rekomendacja:

- `prepare_chat` robi wszystkie zapisy i commit przed `execute_chat`,
- `execute_chat` pracuje juz na trwale zapisanym stanie,
- runner w etapie 2 dostanie osobna odpowiedzialnosc za swoje transakcje.

To upraszcza debugowanie i zmniejsza liczbe przypadkow posrednich.

### 13. Dodac testy etapu 1

Minimalny zestaw testow:

- tworzenie nowej sesji przy pustym `session_id`,
- zwrot bledu przy nieistniejacym `session_id`,
- merge `agent_config` z runtime root agentem,
- utworzenie root agenta dla nowej sesji,
- wyliczenie `last_sequence` przed zapisem inputu,
- zapis pustego `input=[]` bez bledu,
- zapis `message`,
- filtracja odpowiedzi po `last_sequence`,
- odpowiedz `not implemented` dla `stream=True`.

## Kolejnosc pracy

Rekomendowana kolejnosc wdrozenia:

1. Poprawic schema i endpoint chat.
2. Dodac modele request/response i pomocnicze typy serwisu.
3. Dolozyc helper runtime root agent config.
4. Uzupelnic repozytoria o brakujace helpery:
   `create/get/save/get_last_sequence/list_visible_after_sequence` albo ich odpowiedniki.
5. Zaimplementowac `ChatService.prepare_chat`.
6. Zaimplementowac `ChatService.execute_chat` z placeholderem runnera.
7. Dopiac mapper odpowiedzi.
8. Napisac testy etapu 1.

## Kryteria akceptacji etapu 1

Etap uznajemy za zamkniety, gdy:

- endpoint przyjmuje nowy kontrakt requestu,
- `ChatService.process_chat(...)` dziala end-to-end bez runnera,
- sesja i root agent sa poprawnie tworzone lub ladowane,
- `last_sequence` jest liczone przed zapisem inputu,
- wszystkie `input items` sa zapisywane,
- odpowiedz zawiera tylko nowe itemy widoczne dla uzytkownika,
- `stream=True` ma jawne zachowanie tymczasowe,
- kod jest gotowy do podpiecia `runner.run_agent(...)` bez zmiany kontraktu `ChatService`.

## Poza zakresem tego dokumentu

Ten dokument celowo nie rozpisuje jeszcze:

- petli `runner.py`,
- providera LLM,
- `execute_turn`,
- `handle_turn_response`,
- tool execution,
- waiting/resume,
- streaming eventow.

To trafi do osobnego dokumentu dla etapu 2.
