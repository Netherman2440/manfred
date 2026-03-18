# Specyfikacja migracji przykładu `01_05_agent` z TypeScript do Pythona

## Plan implementacji

Statusy używane w planie: `todo`, `in progress`, `done`.

1. `todo` Ustalić i zaimplementować warstwę domenową dla aktualnego zakresu:
   `ChatRequest`, `User`, `Session`, `Agent`, `Item`, `PreparedChat`.
2. `todo` Zbudować warstwę persistence:
   modele SQLAlchemy, przy czym każdy model ma trafić do osobnego pliku w `src/app/db/models/`.
3. `todo` Przygotować inicjalną migrację bazy danych:
   pierwsza migracja ma utworzyć tabele potrzebne dla `User`, `Session`, `Agent` i `Item`.
4. `todo` Dodać warstwę repozytoriów w `src/app/db/repositories/`:
   po jednym repozytorium na model, wyłącznie z czystym CRUD-em, bez składania logiki biznesowej między modelami.
5. `todo` Dodać serwisy aplikacyjne w `src/app/services/`:
   w szczególności `session_service` z metodą `create_session(msg)` oraz rejestrację serwisów w kontenerze DI tak, aby były wstrzykiwane do API przez `Depends`.
6. `todo` Zaimplementować `POST /api/chat/completions` w ograniczonym zakresie:
   request ma przyjmować tylko `message` oraz opcjonalne `sessionId`; gdy `sessionId` nie zostanie podane, endpoint tworzy nową sesję.
7. `todo` Przygotować składanie kontekstu wejściowego agenta w `chat_service.py` bez uruchamiania pętli wykonania:
   utworzyć `PreparedChat`, ładować `agent config` z kontenera, wyznaczać `tools` na podstawie konfiguracji agenta, budować `agent input` tak, aby system prompt nie trafiał do sesji, trzymać `task` w konfiguracji agenta i na razie ładować samą sesję bez itemów.
8. `todo` Kolejny krok:
   zaimplementować pętlę wykonywania agenta; rozpisanie tej pętli i jej implementacja są celowo odłożone do następnego etapu prac.

## Cel dokumentu

Celem jest opisanie pełnego zakresu przykładu `4th-devs/01_05_agent` w formie specyfikacji dla implementacji w repozytorium `manfred`. Dokument koncentruje się na zachowaniu systemu, architekturze oraz kluczowych elementach pętli agenta, a nie na translacji 1:1 kodu TypeScript.

Przenoszony system ma pozostać:

- serwerem HTTP do uruchamiania agentów AI,
- systemem sesyjnym z trwałą historią rozmów,
- runtime'em wieloagentowym z narzędziami, MCP i human-in-the-loop,
- przykładem pokazującym zarządzanie jawnymi i niejawnymi limitami modeli.

## Kontekst migracji

Przykład z lekcji `obsidian/aidevs/s01e05-zarzadzanie-jawnymi-oraz-niejawnymi-limitami-modeli-1773377197.md` pokazuje nie tylko samo wywołanie modelu, ale pełną architekturę produkcyjnego agenta:

- ochronę endpointów i limitowanie ruchu,
- kontrolę nad długością i kosztem kontekstu,
- wieloetapową pętlę agenta z narzędziami,
- zatrzymywanie i wznawianie pracy,
- integrację z wieloma providerami,
- delegowanie pracy do innych agentów,
- monitoring i śledzenie zdarzeń.

Implementacja pythonowa ma zachować te założenia na poziomie produktu i architektury.

## Zakres migracji

Migracja ma objąć wszystkie elementy zaimplementowane w przykładzie:

- serwer API z middleware i endpointami chat/MCP/health,
- konfigurację środowiskową i inicjalizację runtime,
- model domenowy: użytkownik, sesja, agent, item,
- repozytoria i trwałość danych,
- mechanikę sesji i wieloturnowej rozmowy,
- pętlę wykonania agenta wraz ze stanami i wznowieniami,
- abstrakcję providerów LLM,
- rejestr i wykonanie narzędzi,
- obsługę narzędzi dedykowanych oraz MCP,
- mechanizmy kontroli limitów i kontekstu,
- streaming,
- obserwowalność, logowanie i tracing,
- graceful shutdown.

## Poza zakresem

Ten dokument nie specyfikuje:

- dokładnego mapowania klas i plików TS na pliki Python,
- wyboru konkretnej biblioteki do MCP lub SDK providerów, o ile zachowany jest kontrakt systemowy,
- rozbudowy przykładu o funkcje nieobecne w oryginale, np. panel użytkownika, kolejki zadań, GUI czy deployment.

## Docelowa wizja systemu

`manfred` ma być backendem agentowym opartym o Pythona, który przyjmuje żądania HTTP, uruchamia lub wznawia sesje agentów, utrzymuje historię i stan w SQLite, korzysta z różnych providerów modeli i pozwala agentowi używać narzędzi lokalnych, MCP oraz narzędzi wymagających udziału człowieka.

System ma rozdzielać:

- warstwę HTTP,
- runtime agenta,
- abstrakcję providerów,
- abstrakcję narzędzi,
- trwałość stanu,
- obserwowalność.

To rozdzielenie jest istotne, ponieważ przykład celowo nie wiąże logiki agenta z jednym frameworkiem AI ani z jednym providerem.

## Główne komponenty systemu

### 1. Warstwa HTTP

Warstwa HTTP odpowiada za:

- przyjęcie żądania od klienta,
- walidację payloadu,
- autoryzację użytkownika,
- rate limiting,
- timeout i limity rozmiaru requestu,
- uruchomienie właściwego przepływu runtime,
- zwrócenie odpowiedzi synchronicznej albo strumieniowanej,
- ekspozycję endpointów do wznowienia pracy agenta i autoryzacji MCP.

Docelowo w Pythonie warstwa ta powinna być zaimplementowana idiomatycznie dla `FastAPI`, ale bez mieszania jej z logiką domenową.

### 2. Runtime agenta

Runtime jest sercem systemu. Odpowiada za:

- zbudowanie kompletnego kontekstu uruchomienia,
- odczyt konfiguracji agenta i sesji,
- prowadzenie pętli agentowej,
- wywołanie providera modelu,
- zapis elementów rozmowy,
- wykonanie narzędzi,
- przejście w stan `waiting`,
- wznowienie po dostarczeniu wyniku,
- automatyczne propagowanie wyników dziecka do rodzica w delegacji.

### 3. Provider abstraction

System musi posiadać wspólny interfejs dla providerów modeli. Oryginał wspiera:

- OpenAI-compatible Responses API,
- OpenRouter jako wariant providera OpenAI-compatible,
- Gemini Interactions API.

Abstrakcja ma ujednolicać:

- format wejścia,
- format wyjścia,
- wywołania narzędzi,
- reasoning,
- usage,
- streaming events.

Kluczowe jest to, że reszta systemu nie powinna znać specyfiki konkretnego API providera.

### 4. Tooling abstraction

System musi rozróżniać kilka klas narzędzi:

- `sync` - wykonanie natychmiastowe w ramach tej samej pętli,
- `human` - zatrzymanie pracy i oczekiwanie na odpowiedź użytkownika,
- `agent` - delegowanie zadania do innego agenta,
- `async` lub zewnętrzne - pozostawienie zadania w stanie oczekiwania na późniejsze dostarczenie wyniku.

Narzędzia muszą być rejestrowane centralnie i dostarczane agentowi jako jawna lista definicji.

### 5. MCP integration

System ma wspierać narzędzia pochodzące z serwerów MCP:

- uruchamianych lokalnie przez stdio,
- dostępnych zdalnie po HTTP,
- opcjonalnie wymagających OAuth.

MCP ma być traktowane jako kolejny typ źródła narzędzi, a nie osobna ścieżka logiki agentowej.

### 6. Persistence

Trwałość danych jest częścią logiki systemu, a nie dodatkiem. Należy utrzymać zapis:

- użytkowników,
- sesji,
- agentów,
- itemów rozmowy.

Historia ma być kompletna i zachowana nawet wtedy, gdy kontekst przekazywany do modelu jest skracany.

### 7. Observability

System ma emitować zdarzenia domenowe i operacyjne opisujące:

- start i koniec pracy agenta,
- początek i koniec tur,
- wywołania modelu,
- wywołania narzędzi,
- przejście w `waiting`,
- wznowienie po `deliver`.

Na tych zdarzeniach mają opierać się:

- logowanie strukturalne,
- tracing,
- integracja z Langfuse.

## Model domenowy

### Użytkownik

Użytkownik identyfikowany jest przez API key przechowywany w bazie w postaci hasha. Użytkownik stanowi tenant dla:

- autoryzacji,
- sesji,
- limitów ruchu,
- atrybucji w trace'ach.

### Sesja

Sesja reprezentuje rozmowę użytkownika i ma:

- własne ID,
- właściciela,
- opcjonalne podsumowanie starszego kontekstu,
- referencję do głównego agenta rozmowy.

Sesja jest nośnikiem ciągłości rozmowy niezależnie od wybranego providera.

### Agent

Agent jest instancją wykonania zadania. Musi przechowywać:

- ID,
- powiązanie z sesją,
- stan wykonania,
- prompt zadania,
- konfigurację modelu i narzędzi,
- licznik tur,
- usage,
- relacje hierarchiczne `root/parent/child`,
- listę oczekiwań `waitingFor`.

Agent nie jest tylko definicją z pliku markdown. Jest konkretną instancją runtime z własnym stanem.

### Item

Item jest atomową jednostką historii rozmowy. System musi wspierać co najmniej:

- wiadomości `user/assistant/system`,
- function call,
- function call output,
- reasoning.

Itemy są źródłem prawdy dla:

- odbudowy kontekstu,
- generowania odpowiedzi API,
- audytu,
- kompresji historii.

## Stany i cykl życia agenta

Agent musi wspierać pełny cykl życia:

- `pending`,
- `running`,
- `waiting`,
- `completed`,
- `failed`,
- `cancelled`.

Wymagane przejścia:

- nowy lub resetowany agent startuje jako `pending`,
- po uruchomieniu przechodzi do `running`,
- jeśli model oczekuje na wynik narzędzia lub człowieka, przechodzi do `waiting`,
- po dostarczeniu wszystkich brakujących wyników wraca do `running`,
- po uzyskaniu końcowej odpowiedzi przechodzi do `completed`,
- w przypadku błędu przechodzi do `failed`,
- w przypadku anulowania do `cancelled`.

Specyfikacja Python musi zachować te stany i ich semantykę, bo są podstawą mechanizmu resume.

## Definicja agenta w workspace

Definicja agenta ma pozostać zewnętrzna wobec kodu i być trzymana w pliku markdown z frontmatterem. Taka definicja zawiera:

- nazwę,
- model,
- listę narzędzi,
- treść promptu systemowego.

Ważne zachowania do zachowania:

- agent jest ładowany z dysku dynamicznie, bez restartu serwera,
- żądanie może wskazać agenta po nazwie,
- parametry requestu mogą nadpisać ustawienia wynikające z szablonu,
- szablon może odwoływać się zarówno do narzędzi wbudowanych, jak i MCP.

## Składanie kontekstu LLM

Budowanie requestu do modelu jest osobnym etapem systemu i nie powinno być rozproszone po endpointach ani providerach.

Kontekst dla pojedynczego wywołania LLM musi powstawać przez scalenie:

- definicji agenta z pliku markdown,
- override'ów przekazanych w requestcie,
- definicji narzędzi rozwiązanych po nazwach,
- stanu sesji i zapisanych itemów.

Wymagane zasady:

- template jest odczytywany z dysku per request,
- override'y z API mają pierwszeństwo nad wartościami z template,
- lista narzędzi przekazywana do providera zawiera kompletne schemy function calling,
- historia sesji jest częścią wejścia do budowy kontekstu, ale podlega pruningowi i summarization.

## API wymagane przez migrację

### `POST /api/chat/completions`

Główny endpoint uruchamiający turę rozmowy.

Musi wspierać:

- wybór agenta przez nazwę albo bezpośrednie podanie modelu/instrukcji,
- input tekstowy lub strukturalny,
- `sessionId` do wznowienia rozmowy,
- streaming SSE,
- jawne przekazanie modelu, temperatury, limitu tokenów i narzędzi.

Odpowiedź niestrumieniowana musi zwracać:

- `sessionId`,
- `agentId`,
- status `completed` lub `waiting`,
- wygenerowane elementy odpowiedzi,
- `waitingFor`, gdy agent oczekuje na zewnętrzne dostarczenie wyniku.

Jeśli agent wszedł w `waiting`, endpoint zwraca semantycznie stan oczekiwania, a nie błąd.

### `POST /api/chat/agents/:agentId/deliver`

Endpoint do dostarczenia wyniku do oczekującego agenta. Musi obsługiwać:

- rezultat poprawny,
- rezultat błędny,
- wznowienie pracy agenta po dostarczeniu,
- auto-propagację wyniku do rodzica, jeśli czekające wywołanie pochodziło z delegacji.

### `GET /api/chat/agents/:agentId`

Endpoint statusowy musi umożliwiać odczyt:

- statusu agenta,
- listy brakujących wyników,
- głębokości delegacji,
- relacji rodzic-dziecko,
- licznika tur.

### `GET /api/mcp/servers`

Lista skonfigurowanych serwerów MCP oraz ich statusów.

### `GET /api/mcp/:server/auth`

Pobranie URL autoryzacyjnego dla serwera MCP wymagającego OAuth.

### `GET /mcp/:server/callback`

Publiczny callback kończący autoryzację MCP i prezentujący rezultat w prostej stronie HTML.

### `GET /health`

Endpoint zdrowia aplikacji ma raportować co najmniej:

- dostępność runtime,
- łączność z warstwą persistence.

## Wysokopoziomowy przepływ pojedynczego requestu chat

1. Klient wysyła request do `/api/chat/completions`.
2. Middleware nadaje request ID, nakłada nagłówki bezpieczeństwa, CORS, body limit, timeout.
3. Żądanie przechodzi przez autoryzację Bearer i rate limiter.
4. Warstwa chat ładuje runtime i waliduje payload.
5. System rozwiązuje konfigurację agenta: template, model, prompt, listę narzędzi.
6. System wczytuje istniejącą sesję albo tworzy nową.
7. System wybiera lub tworzy głównego agenta sesji.
8. Nowy input użytkownika zostaje zapisany jako item.
9. Runtime uruchamia pętlę agenta.
10. Provider generuje odpowiedź modelu.
11. Odpowiedź zostaje zapisana jako itemy.
12. Jeśli są wywołania narzędzi, runtime je realizuje albo przechodzi w `waiting`.
13. Jeśli nie ma dalszej pracy, agent kończy się jako `completed`.
14. Warstwa HTTP zwraca odpowiedź zwykłą albo SSE.

## Pętla agenta

Pętla agenta jest najważniejszym elementem migracji i musi zostać zachowana koncepcyjnie.

### Wejście do tury

Każda tura rozpoczyna się od:

- odczytu stanu agenta,
- odczytu sesji,
- odbudowy historii itemów,
- sprawdzenia limitów kontekstu,
- zbudowania ujednoliconego inputu dla providera.

### Wywołanie modelu

Provider otrzymuje:

- model,
- instructions/system prompt,
- input conversation items,
- listę narzędzi,
- ustawienia generacji,
- sygnał anulowania.

### Zapis odpowiedzi

Wynik modelu musi zostać rozbity na itemy i zapisany. Dotyczy to:

- tekstu asystenta,
- function calls,
- reasoning.

### Obsługa tool calls

Po odpowiedzi modelu runtime analizuje wszystkie wywołania narzędzi:

- narzędzia synchroniczne wykonuje od razu i zapisuje ich wynik,
- narzędzia `human` odkłada do `waitingFor`,
- delegację realizuje przez utworzenie dziecka i uruchomienie jego własnej pętli,
- narzędzia MCP wywołuje bezpośrednio przez manager MCP,
- nieobsłużone narzędzia traktuje jako zewnętrzne i oczekuje na `deliver`.

### Decyzja o kontynuacji

Po zakończeniu obsługi narzędzi pętla:

- idzie do kolejnej tury, jeśli dostępne są nowe wyniki i agent może pracować dalej,
- kończy pracę, jeśli model nie oczekuje dalszych wywołań,
- przechodzi do `waiting`, jeśli potrzebne są dane z zewnątrz.

### Resume

Po `deliver` system:

- dopisuje `function_call_output`,
- usuwa z `waitingFor` dostarczony element,
- jeśli nadal czegoś brakuje, pozostaje w `waiting`,
- jeśli wszystkie wyniki zostały dostarczone, ponownie uruchamia pętlę od kolejnej tury.

## Delegacja i wieloagentowość

System musi zachować delegację jako mechanizm pierwszej klasy.

Delegacja polega na:

- wywołaniu narzędzia `delegate`,
- utworzeniu agenta podrzędnego w tej samej sesji,
- przekazaniu mu zadania jako wiadomości użytkownika,
- uruchomieniu jego pętli we własnym kontekście wykonania,
- zwróceniu końcowego rezultatu do rodzica jako wynik function call.

Wymagane ograniczenia:

- kontrola maksymalnej głębokości delegacji,
- zachowanie trace context między rodzicem a dzieckiem,
- możliwość przejścia dziecka w `waiting`,
- auto-propagacja wyniku dziecka po ukończeniu.

Dodatkowo system musi wspierać `send_message`, czyli nieblokujące wysłanie informacji do innego agenta przez dopisanie wiadomości do jego historii.

## Narzędzia wbudowane

Migracja musi objąć semantykę wszystkich narzędzi obecnych w przykładzie:

- `calculator` - natychmiastowe wykonanie obliczenia,
- `delegate` - delegacja zadania do innego agenta,
- `send_message` - nieblokująca komunikacja między agentami,
- `ask_user` - zatrzymanie pracy i oczekiwanie na odpowiedź człowieka,
- `web_search` - natywne narzędzie providera,
- narzędzia MCP o nazwach `server__tool`.

Istotne jest zachowanie podziału na definicję narzędzia i jego rzeczywiste wykonanie. W przykładzie część narzędzi ma "pusty" handler walidacyjny, a rzeczywista logika dzieje się w runnerze. W Pythonie nie trzeba kopiować tej techniki, ale trzeba zachować to samo zachowanie systemowe.

## Providerzy i normalizacja odpowiedzi

Migracja ma zachować wspólny kontrakt dla providerów, niezależnie od różnic między OpenAI-compatible i Gemini.

System musi umieć znormalizować:

- wiadomości tekstowe,
- function calls i function results,
- reasoning,
- usage,
- eventy streamingu.

Dodatkowo:

- model ma być wskazywany w formacie `provider:model`,
- dobór providera musi wynikać z prefiksu modelu,
- możliwe musi być współistnienie wielu providerów w jednym runtime,
- system powinien pozostać otwarty na kolejnych providerów bez przebudowy pętli agenta.

## Zarządzanie kontekstem i limitami

To jest jeden z głównych celów przykładu i migracja musi go zachować wprost.

### Limity jawne

System ma egzekwować jawne ograniczenia:

- rozmiar request body,
- timeout requestu,
- rate limit na użytkownika,
- maksymalną liczbę tur agenta,
- maksymalną głębokość delegacji,
- timeout wywołania narzędzia MCP,
- limity wynikające z konfiguracji modeli.

### Limity niejawne

System ma aktywnie adresować ograniczenia, których użytkownik zwykle nie widzi:

- ograniczone okno kontekstowe modeli,
- wzrost kosztu przy długiej historii,
- ryzyko nadmiernie dużych outputów narzędzi,
- zanieczyszczenie kontekstu mało istotnymi danymi,
- błędy wynikające z przekazania modelowi zbyt dużej ilości informacji.

### Strategia kompresji kontekstu

Wymagane zachowania:

- estymacja zużycia tokenów dla bieżącej historii,
- truncation bardzo dużych outputów narzędzi,
- zachowanie najnowszych tur rozmowy,
- odrzucanie starszych tur po przekroczeniu progu,
- opcjonalne uzupełnienie odrzuconego kontekstu podsumowaniem generowanym przez model,
- przechowywanie pełnej historii w bazie niezależnie od tego, co trafia do aktualnego promptu.

Ta część jest kluczowa, ponieważ realizuje główne przesłanie lekcji: model nie powinien otrzymywać całej historii bez kontroli.

## Streaming

System musi wspierać tryb strumieniowany dla chat completion.

Streaming ma przekazywać ujednolicone eventy opisujące:

- przyrosty tekstu,
- ukończony tekst,
- przyrosty argumentów function call,
- ukończone function calls,
- reasoning,
- końcowy wynik lub błąd.

Streaming nie zastępuje persistence. Strumień jest tylko kanałem do klienta; źródłem prawdy pozostają zapisane itemy i stan agenta.

## Kontrakt zdarzeń i przebieg event flow

Zdarzenia są częścią architektury systemu, a nie wyłącznie implementacją logowania. Pythonowa migracja ma je traktować jako stabilny kontrakt wewnętrzny runtime.

Każde zdarzenie powinno zawierać wspólny kontekst korelacyjny, co najmniej:

- `traceId`,
- `sessionId`,
- `agentId`,
- `rootAgentId`,
- `parentAgentId` jeśli istnieje,
- `depth`,
- timestamp zdarzenia.

Minimalny katalog zdarzeń do zachowania:

- `agent.started`,
- `turn.started`,
- `tool.called`,
- `tool.completed`,
- `tool.failed`,
- `turn.completed`,
- `agent.waiting`,
- `agent.resumed`,
- `agent.completed`,
- `agent.failed`,
- `agent.cancelled`,
- zdarzenia związane z generacją modelu,
- zdarzenia związane ze streamingiem.

Typowy przebieg dla zakończonej tury powinien wyglądać następująco:

1. `agent.started`
2. `turn.started`
3. `generation.completed`
4. zero lub więcej par `tool.called` i `tool.completed` albo `tool.failed`
5. `turn.completed`
6. `agent.completed` albo kolejne `turn.started`

Typowy przebieg dla stanu oczekiwania:

1. `agent.started`
2. `turn.started`
3. `generation.completed`
4. `turn.completed`
5. `agent.waiting`
6. po `deliver`: `agent.resumed`
7. wznowienie kolejnej tury albo `agent.completed`

Ważne konsekwencje projektowe:

- logowanie, tracing i monitoring mają być budowane na bazie tych zdarzeń,
- zdarzenia muszą opisywać zarówno sukces, jak i błąd narzędzia,
- delegacja ma zachowywać ciągłość korelacji między parent i child agentem,
- event stream nie może zależeć od konkretnego providera.

## Bezpieczeństwo i kontrola dostępu

Pythonowa wersja musi zachować następujące założenia:

- wszystkie ścieżki API poza publicznym callbackiem MCP są chronione Bearer tokenem,
- token użytkownika jest weryfikowany przez hash w bazie,
- limitowanie ruchu działa per użytkownik,
- konfiguracja środowiska jest walidowana na starcie,
- endpointy modelowe są traktowane jako szczególnie wrażliwe operacyjnie,
- błędy zwracane do klienta nie powinny ujawniać nadmiaru szczegółów w środowisku produkcyjnym.

## Runtime startup i shutdown

Podczas startu system musi:

- wczytać i zwalidować konfigurację,
- zarejestrować providerów,
- uruchomić połączenie z bazą danych,
- zainicjalizować rejestr narzędzi,
- połączyć serwery MCP,
- załadować listę dostępnych agentów workspace,
- podłączyć subskrybentów zdarzeń.

Podczas zamykania system musi:

- przestać przyjmować nowe połączenia,
- domknąć zasoby runtime,
- zamknąć połączenia MCP,
- wypchnąć tracing i logi, jeśli to możliwe.

## Decyzje techniczne dla implementacji w `manfred`

Poniższe decyzje techniczne stanowią część docelowej specyfikacji migracji dla repozytorium `manfred`.

### Stos aplikacyjny

Docelowy stos ma być następujący:

- `FastAPI` dla warstwy HTTP,
- `Pydantic` dla schematów API i konfiguracji,
- `SQLAlchemy ORM` dla modeli persistence,
- `Alembic` dla migracji bazy,
- kontener zależności w `container.py` jako centralny punkt składania aplikacji.

Migracja nie ma odtwarzać `drizzle`, tylko zachowanie systemu na bazie idiomatycznego stosu Pythona.

### Konfiguracja

Zasady konfiguracji:

- wszystkie zmienne środowiskowe mają być mapowane do `config.py`,
- `config.py` może zawierać bezpieczne wartości domyślne tam, gdzie to uzasadnione,
- kod aplikacji powinien czytać ustawienia z configu, nie bezpośrednio z `os.environ`,
- każda zmiana w konfiguracji wymaga aktualizacji pliku `.env.EXAMPLE`.

### Kontener zależności

`container.py` ma być źródłem prawdy dla obiektów współdzielonych w aplikacji. To tam powinny być definiowane:

- konfiguracja aplikacji,
- providerzy LLM,
- runtime state,
- repozytoria,
- rejestr narzędzi,
- zewnętrzne serwisy używane przez narzędzia,
- inne singletony i fabryki potrzebne podczas działania aplikacji.

Zasady użycia:

- w endpointach FastAPI zależności wstrzykujemy przez `Depends()`,
- obiekty dostarczane do endpointów mają pochodzić z kontenera,
- nie tworzymy providerów, repozytoriów i serwisów ad hoc wewnątrz route handlerów,
- przekazywanie configu do zależności ma być scentralizowane w kontenerze.

### Narzędzia

Zasady organizacji tooli:

- jeden tool to jeden plik,
- definicja narzędzia i handler pozostają rozdzielone w obrębie tego samego pliku,
- jeśli kilka tooli dotyczy jednego obszaru, powinny leżeć we wspólnym podkatalogu `src/app/agent/tools`,
- tool może zależeć od zewnętrznych serwisów, ale te zależności mają być dostarczane przez kontener,
- rejestracja tooli dostępnych dla runtime ma być wykonywana centralnie w kontenerze.

To oznacza, że kontener odpowiada zarówno za:

- konstrukcję serwisów potrzebnych przez toole,
- konstrukcję instancji tooli,
- zdefiniowanie listy tooli aktywnych w danym uruchomieniu aplikacji.

### Persistence i migracje

Zasady dla warstwy danych:

- modele persistence definiujemy w SQLAlchemy ORM,
- zmiany schematu wprowadzamy przez Alembic,
- schema runtime i migracje muszą pozostać ze sobą spójne,
- warstwa repozytoriów pozostaje oddzielona od modeli API i od logiki endpointów.

## Obserwowalność

Migracja ma zachować event-driven observability. Nie chodzi tylko o logowanie błędów, ale o pełną narrację przebiegu działania agenta.

Wymagane klasy zdarzeń:

- lifecycle agenta,
- lifecycle tury,
- generacja modelu,
- wykonanie narzędzia,
- waiting/resume,
- zdarzenia streamingu.

Na tej podstawie system powinien wspierać:

- logowanie strukturalne,
- korelację po `traceId`,
- podpięcie Langfuse jako opcjonalnej integracji,
- obserwowalność hierarchii agentów i zależności parent-child.

## Wymagania architektoniczne dla wersji Python

Docelowa implementacja w `manfred` powinna:

- zachować separację warstw HTTP, runtime, domain, providers, tools i repositories,
- pozostać niezależna od jednego frameworka AI,
- traktować persistence jako integralny element systemu,
- wspierać obecny stos repozytorium, tj. `FastAPI`, `Pydantic Settings`, `SQLAlchemy` i DI,
- umożliwiać dalszy rozwój bez przebudowy fundamentów pętli agenta.

Minimalny rezultat migracji nie powinien być tylko "chat endpointem do LLM", ale działającym systemem agentowym z pamięcią, narzędziami, resume i kontrolą limitów.

## Kryteria akceptacji

Migrację można uznać za zgodną z tą specyfikacją, jeśli system Python:

- potrafi uruchomić agenta z definicji markdown,
- utrzymuje wieloturnową sesję z trwałą historią,
- zapisuje agentów, sesje i itemy w SQLite,
- wspiera co najmniej dwóch providerów w ramach wspólnego interfejsu,
- realizuje synchroniczne narzędzia, delegację, `ask_user`, `send_message` i MCP,
- potrafi przejść w `waiting` i wznowić pracę przez `deliver`,
- obsługuje streaming oraz zwykły tryb odpowiedzi,
- stosuje pruning i summarization przy wzroście kontekstu,
- egzekwuje auth, timeout, body limit i rate limiting,
- emituje zdarzenia oraz nadaje się do podpięcia pod tracing.

## Podsumowanie

Przykład `01_05_agent` nie jest jedynie wrapperem na API modelu. To pełny szkielet backendu agentowego, którego najważniejsze elementy to:

- trwały stan rozmowy,
- kontrolowana pętla wykonania,
- narzędzia i interakcja z otoczeniem,
- możliwość zatrzymania i wznowienia,
- ograniczanie kosztu i rozmiaru kontekstu,
- wieloagentowość,
- obserwowalność.

To właśnie ten poziom zachowania należy przenieść do `manfred`, a nie samą składnię rozwiązań z TypeScript.
