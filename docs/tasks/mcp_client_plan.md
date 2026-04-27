# Plan implementacji MCP clienta w `manfred`

Ten dokument opisuje, jak dolozyc do `manfreda` warstwe MCP clienta wzorowana na `4th-devs/01_05_agent`, ale dopasowana do obecnej architektury Pythona.

Glowny cel: agent ma umiec korzystac z tooli dostarczanych przez serwery MCP, w pierwszej kolejnosci z `files-mcp`, tak zeby w definicji agenta mozna bylo wpisac np.:

```yaml
tools:
  - files__fs_read
  - files__fs_search
  - files__fs_write
```

## Referencje

- wzorzec architektoniczny: `<reference-repo>/src/mcp/client.ts`
- integracja z loaderem agenta: `<reference-repo>/src/workspace/loader.ts`
- wykonanie MCP tooli w petli: `<reference-repo>/src/runtime/runner.ts`
- obecny loader agenta w Pythonie: `src/app/services/agent_loader.py`
- obecny runner w Pythonie: `src/app/runtime/runner.py`
- obecny kontener DI: `src/app/container.py`

## Stan obecny `manfreda`

Obecny kod ma juz dwa dobre punkty integracji:

- `AgentLoader` rozwiazuje nazwy tooli z frontmatteru agenta do `ToolDefinition`.
- `Runner` wykonuje function calle zwrocone przez providera i zapisuje `function_call_output`.

Brakuje jednak warstwy posredniej, ktora:

- wczyta konfiguracje MCP,
- nawiaze polaczenia do serwerow MCP,
- wystawi liste dostepnych MCP tooli w formacie zgodnym z providerem,
- wykona MCP tool call w runtime,
- poda status serwera i ewentualnie stan autoryzacji.

To oznacza, ze MCP powinno wejsc jako osobny komponent runtime, a nie jako rozszerzenie `ToolRegistry`.

## Docelowy ksztalt architektury

Rekomendowany podzial odpowiedzialnosci:

### 1. `app/mcp`

Nowy pakiet odpowiedzialny za:

- typy i modele konfiguracji MCP,
- loader pliku `.mcp.json`,
- lifecycle klientow MCP,
- listowanie tooli,
- wykonywanie `call_tool(...)`,
- statusy polaczen,
- opcjonalnie OAuth dla serwerow HTTP.

### 2. `AgentLoader`

`AgentLoader` nie powinien znac implementacji transportu MCP.
Powinien dostac tylko zaleznosc typu `McpManager` i umiec:

- rozpoznac nazwe w formacie `server__tool`,
- pobrac definicje MCP toola,
- zwrocic `FunctionToolDefinition`, tak samo jak dla lokalnych tooli.

### 3. `Runner`

`Runner` powinien:

- najpierw sprawdzic lokalny `ToolRegistry`,
- jesli tool nie jest lokalny, sprawdzic czy jest poprawna nazwa MCP,
- wykonac go przez `McpManager`,
- zapisac wynik jako zwykly `function_call_output`,
- emitowac te same eventy co dla lokalnych tooli: `tool.called`, `tool.completed`, `tool.failed`.

### 4. HTTP API

Warstwa API nie jest potrzebna do pierwszego MVP ze `stdio files-mcp`, ale jest potrzebna do ergonomii i kolejnych etapow.
Docelowo warto miec:

- `GET /api/v1/mcp/servers`
- opcjonalnie `GET /api/v1/mcp/{server}/auth`
- opcjonalnie callback OAuth dla transportu HTTP

## Zakres MVP

Zeby nie przepalic czasu na pelny MCP od razu, rekomendowany pierwszy zakres jest taki:

1. tylko serwery `stdio`
2. tylko lokalny plik konfiguracyjny `.mcp.json`
3. tylko listowanie tooli i wykonywanie tool calli
4. bez HTTP transportu
5. bez OAuth
6. bez osobnych endpointow API

To wystarczy, zeby agent w `manfredzie` zaczal korzystac z `files-mcp`.

## Rekomendowany kontrakt `McpManager`

Warto od razu zamknac MCP za jednym interfejsem aplikacyjnym:

```python
class McpManager(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    def servers(self) -> list[str]: ...
    def server_status(self, name: str) -> str: ...
    def parse_name(self, prefixed_name: str) -> tuple[str, str] | None: ...
    async def list_tools(self) -> list[McpToolInfo]: ...
    async def list_server_tools(self, server_name: str) -> list[McpToolInfo]: ...
    async def get_tool(self, prefixed_name: str) -> McpToolInfo | None: ...
    async def call_tool(
        self,
        prefixed_name: str,
        arguments: dict[str, object],
        signal: object | None = None,
    ) -> str: ...
```

Pomocniczy model `McpToolInfo` powinien trzymac:

- `server`
- `original_name`
- `prefixed_name`
- `description`
- `input_schema`

Separator `__` warto zachowac taki sam jak w `4th-devs`, bo upraszcza kompatybilnosc z definicjami agentow.

## Format konfiguracji

Rekomendacja: zachowac format kompatybilny z przykladem `01_05_agent`.

Plik: `.mcp.json` w root repozytorium `manfred`.

Przykladowy minimalny config dla `files-mcp`:

```json
{
  "mcpServers": {
    "files": {
      "transport": "stdio",
      "command": "node",
      "args": [
        "<files-mcp-repo>/dist/index.js"
      ],
      "env": {
        "FS_ROOTS": "<repo-root>/.agent_data,<repo-root>/docs"
      },
      "cwd": "<repo-root>"
    }
  }
}
```

Uwagi:

- w MVP konfiguracja moze byc tylko odczytywana, bez zapisu do DB,
- `cwd` powinno byc jawne, zeby proces MCP mial stabilny katalog roboczy,
- dla `files-mcp` bezpieczniej jest ograniczyc `FS_ROOTS` do wybranych katalogow, zamiast dawac dostep do calego repo.

## Plan implementacji

### Etap 1. Dodac pakiet `app/mcp`

Nowe pliki:

- `src/app/mcp/__init__.py`
- `src/app/mcp/types.py`
- `src/app/mcp/config.py`
- `src/app/mcp/client.py`

Zakres:

- zdefiniowac typy `McpConfig`, `McpServerConfig`, `McpToolInfo`,
- zaimplementowac loader `.mcp.json`,
- obsluzyc brak pliku jako `mcpServers = {}`,
- dodac parse nazwy `server__tool`.

Kryterium akceptacji:

- aplikacja startuje poprawnie bez `.mcp.json`,
- bledny JSON daje czytelny blad startowy,
- manager umie sparsowac nazwe `files__fs_read`.

### Etap 2. Zaimplementowac lifecycle klientow `stdio`

Zakres:

- przy starcie runtime utworzyc klienta per serwer MCP,
- nawiazac polaczenia do wszystkich serwerow z `.mcp.json`,
- przechowac klientow w `McpManager`,
- dodac timeout wywolania MCP toola,
- znormalizowac output do `str`, tak jak robi to referencyjny `01_05_agent`.

Zmiany w kodzie:

- dodac provider lub singleton MCP do `src/app/container.py`,
- dodac ustawienie typu `MCP_CONFIG_PATH` albo wyprowadzic sciezke z root repo,
- wpiac `close()` w lifecycle aplikacji w `src/app/main.py`.

Kryterium akceptacji:

- `McpManager.start()` nawiazuje polaczenie z `files-mcp`,
- `list_tools()` zwraca prefiksowane nazwy typu `files__fs_read`,
- `close()` konczy procesy potomne bez zostawiania zombie.

### Etap 3. Wpiac MCP do `AgentLoader`

Zmiany:

- rozszerzyc konstruktor `AgentLoader`, zeby dostawal `mcp_manager`,
- w `resolve_tool_definitions(...)` obsluzyc narzedzia `server__tool`,
- mapowac MCP tool na `FunctionToolDefinition`.

Wazna decyzja:

- nie rejestrowac MCP tooli w `ToolRegistry`,
- `ToolRegistry` zostaje tylko dla lokalnych tooli,
- `AgentLoader` scala dwa zrodla definicji: lokalne i MCP.

Kryterium akceptacji:

- agent z frontmatterem `files__fs_read` laduje sie bez bledu,
- definicja toola trafia do requestu providera z prawidlowym `parameters`,
- brakujacy MCP tool jest pomijany albo raportowany jawnie w logu.

### Etap 4. Wpiac MCP do `Runner`

Zmiany:

- rozszerzyc `Runner.__init__(...)` o zaleznosc `mcp_manager`,
- w sciezce obslugi function calli dodac branch MCP po nieudanym lookupie w `ToolRegistry`,
- wynik MCP zapisywac do `ItemType.FUNCTION_CALL_OUTPUT`,
- zachowac obecny model eventow i telemetry.

Kryterium akceptacji:

- jesli provider zwroci `files__fs_read`, runner wykona call przez MCP,
- sukces zapisze output jako `function_call_output`,
- blad MCP zapisze `is_error=True` i wyemituje `tool.failed`,
- po zapisie wyniku petla agenta idzie dalej bez zmian w kontrakcie runnera.

### Etap 5. Dolozyc logowanie i statusy

Zakres:

- log na starcie: jakie serwery sa skonfigurowane i jakie toole wystawiaja,
- log na kazdym MCP callu: `server`, `tool`, czas wykonania,
- rozroznienie statusow minimum:
  - `connected`
  - `disconnected`
  - w kolejnym etapie `auth_required`

Kryterium akceptacji:

- przy problemie z MCP wiadomo, czy blad dotyczy configu, polaczenia czy samego toola,
- logi nie mieszaja warstwy lokalnych tooli z MCP.

### Etap 6. Dolozyc testy

Minimalny zestaw testow:

- parser `.mcp.json`,
- `parse_name(...)`,
- mapowanie MCP tooli w `AgentLoader`,
- obsluga MCP toola w `Runner`,
- scenariusz startu bez `.mcp.json`.

Rekomendacja:

- w testach nie odpalac prawdziwego `files-mcp`,
- uzyc fake `McpManager` podobnie jak fake provider w obecnych testach runnera.

### Etap 7. Dopiero potem HTTP i OAuth

To powinien byc osobny etap, nie MVP.

Zakres:

- transport HTTP obok `stdio`,
- persystencja tokenow OAuth,
- endpointy statusowe MCP,
- callback HTTP dla autoryzacji.

Powod:

- to rozszerza surface area aplikacji,
- nie jest potrzebne, zeby odblokowac `files-mcp`,
- istotnie komplikuje lifecycle i testy end-to-end.

## Etap 2. Rozwoj pod zewnetrzne MCP-y typu Google Maps i Google Calendar

Po MVP ze `stdio + files-mcp` kolejny sensowny krok to nie "dodac dowolny transport HTTP", tylko zbudowac warstwe, ktora nadaje sie do serwerow:

- zdalnych,
- per-user,
- wymagajacych OAuth,
- majacych kosztowne albo potencjalnie niebezpieczne akcje.

To jest istotnie inny problem niz lokalny `files-mcp`, bo dochodza:

- credentials zalezne od uzytkownika,
- scope'y OAuth,
- rozne poziomy ryzyka operacji,
- potrzeba potwierdzenia przed zapisem albo wysylka,
- duzo bardziej zmienny stan polaczenia.

### Cel etapu 2

Na koniec tego etapu `manfred` powinien umiec:

- podpiac zdalny serwer MCP po HTTP,
- rozpoznac, czy serwer jest globalny czy user-scoped,
- przeprowadzic flow OAuth dla konkretnego uzytkownika,
- trzymac tokeny poza `.mcp.json`,
- wystawic status polaczenia per serwer i per user,
- odpalac toole typu `maps__search_places` albo `calendar__create_event`,
- rozrozniac operacje read-only i write,
- dla operacji write umiec wejsc w `waiting` albo wymagac explicit confirmation.

### Docelowe typy integracji

Warto od razu rozroznic trzy klasy MCP:

#### 1. Local sandbox MCP

Przyklady:

- `files-mcp`
- lokalne indeksy wiedzy
- lokalne narzedzia developerskie

Charakterystyka:

- najczesciej `stdio`,
- wspolne dla calej instancji aplikacji,
- bez kont uzytkownikow,
- niskie wymagania auth.

#### 2. Shared remote MCP

Przyklady:

- wewnetrzny serwer firmowy do wyszukiwania dokumentacji,
- remote MCP z read-only danymi produktowymi,
- Google Maps przez jedno konto serwisowe, jesli use case jest publiczny i tylko do odczytu.

Charakterystyka:

- najczesciej HTTP,
- jedno polaczenie lub jedna konfiguracja dla calego backendu,
- sekrety trzymane po stronie serwera.

#### 3. User-scoped remote MCP

Przyklady:

- Google Calendar konkretnego usera,
- Gmail,
- Notion,
- Slack,
- Google Maps, jesli zapytania albo historia maja byc atrybuowane per user lub rozliczane osobno.

Charakterystyka:

- auth i tokeny per user,
- czesto OAuth,
- status polaczenia zalezy od usera, nie od calej aplikacji,
- potrzebne potwierdzenia i lepszy audyt.

To rozroznienie warto wprowadzic od razu do architektury, bo bez tego `calendar` i `maps` szybko wymusza przerabianie calego MCP.

## Zmiany architektoniczne potrzebne w etapie 2

### 1. Rozdzielenie konfiguracji serwera od stanu autoryzacji

`.mcp.json` powinno opisywac:

- jakie serwery sa dostepne,
- jaki maja transport,
- czy sa `shared` czy `user_scoped`,
- czy wspieraja OAuth,
- jakie maja wymagane scope'y,
- czy dany serwer jest `read_only`, `mixed`, czy `write_capable`.

Przykladowy kierunek:

```json
{
  "mcpServers": {
    "maps": {
      "transport": "http",
      "url": "https://mcp.example.com/maps",
      "auth": {
        "mode": "oauth",
        "scopes": [
          "maps.read"
        ]
      },
      "ownership": "shared",
      "capabilityMode": "read_only"
    },
    "calendar": {
      "transport": "http",
      "url": "https://mcp.example.com/calendar",
      "auth": {
        "mode": "oauth",
        "scopes": [
          "https://www.googleapis.com/auth/calendar.events"
        ]
      },
      "ownership": "user_scoped",
      "capabilityMode": "mixed"
    }
  }
}
```

Natomiast tokeny i stan sesji OAuth nie powinny byc trzymane w `.mcp.json`.

### 2. Nowy persistence layer dla auth MCP

Do integracji z Google Calendar i podobnymi serwisami potrzebny bedzie nowy model trwalosci, np.:

- `McpConnection`
- `McpCredential`

Minimalne pola:

- `id`
- `user_id`
- `server_name`
- `status`
- `access_token_encrypted`
- `refresh_token_encrypted`
- `scopes`
- `expires_at`
- `created_at`
- `updated_at`

Wazne decyzje:

- tokenow nie trzymac plain textem,
- najlepiej trzymac je szyfrowane kluczem z env,
- status polaczenia ma byc per user i per server.

### 3. `McpManager` musi stac sie context-aware

W MVP manager moze byc globalnym singletonem.
W etapie 2 to juz nie wystarczy.

Potrzebny kierunek:

```python
async def list_tools_for_user(user_id: str) -> list[McpToolInfo]: ...
async def call_tool_for_user(
    user_id: str,
    prefixed_name: str,
    arguments: dict[str, object],
    signal: object | None = None,
) -> str: ...
```

Powod:

- `calendar` moze byc dostepny dla jednego usera, a dla drugiego nie,
- ten sam serwer moze miec inny status auth dla roznych userow,
- `Runner` musi wiedziec, czy moze wykonac tool od razu, czy ma zwrocic stan `auth_required`.

### 4. `ChatService` i `Runner` musza znac prawdziwego usera

Dzis `ChatService` uzywa default usera.
Przed sensownym etapem 2 trzeba to zmienic, bo:

- OAuth do kalendarza musi byc przypisany do konkretnego usera,
- audyt wywolan `calendar__create_event` bez `user_id` jest bezuzyteczny,
- nie da sie poprawnie odroznic "serwer niepolaczony" od "ten user nieautoryzowany".

To oznacza, ze drugi etap MCP praktycznie zaklada rownolegle domkniecie auth usera w API.

### 5. Potrzebny katalog polityk bezpieczenstwa dla tooli

Dla `files-mcp` wystarcza sandbox.
Dla `calendar` i podobnych integracji to za malo.

Warto dodac metadata per tool albo per server:

- `risk_level`: `low`, `medium`, `high`
- `mode`: `read`, `write`
- `confirmation_required`: `true/false`

Przyklady:

- `maps__search_places` -> `read`, `low`, bez confirmation
- `calendar__list_events` -> `read`, `low`, bez confirmation
- `calendar__create_event` -> `write`, `medium`, confirmation required
- `calendar__delete_event` -> `write`, `high`, confirmation required

To mozna trzymac:

- w `.mcp.json`,
- albo w osobnym lokalnym rejestrze polityk po stronie `manfreda`.

Druga opcja jest praktyczniejsza, bo nie wymaga, zeby zewnetrzny serwer MCP opisywal ryzyko w dokladnie takim modelu jak backend.

## Plan implementacji etapu 2

### 2.1. Dodac modele i repozytoria MCP auth

Zakres:

- nowa tabela na polaczenia i tokeny MCP,
- repozytorium odczytu i zapisu credentials,
- warstwa szyfrowania tokenow.

Kryterium akceptacji:

- backend umie zapisac i odczytac token dla `calendar`,
- token nie jest przechowywany jawnym tekstem.

### 2.2. Dodac HTTP transport do `app/mcp`

Zakres:

- klient streamable HTTP,
- timeouty i retry policy,
- rozroznienie `connected`, `auth_required`, `disconnected`, `error`.

Kryterium akceptacji:

- manager laczy sie z serwerem remote MCP,
- bledy auth nie sa raportowane jako zwykle `disconnected`.

### 2.3. Dodac OAuth flow per user

Zakres:

- endpoint startujacy auth dla usera i serwera,
- callback konczacy auth,
- zapis tokenow,
- reconnect klienta po zakonczeniu auth.

Minimalne endpointy:

- `GET /api/v1/mcp/servers`
- `GET /api/v1/mcp/{server}/auth`
- `GET /api/v1/mcp/{server}/callback`

W odpowiedzi `servers` warto zwracac:

- `server`
- `ownership`
- `status`
- `requiresAuth`
- `connectedForUser`

Kryterium akceptacji:

- user moze podpiac swoje konto Google Calendar,
- po callbacku status serwera dla tego usera zmienia sie na `connected`.

### 2.4. Dodac `auth_required` jako stan wykonywania toola

Przyklad:

- agent chce uzyc `calendar__create_event`,
- user nie ma autoryzacji,
- runner nie powinien failowac bezpowrotnie,
- powinien zwrocic kontrolowany stan oczekiwania z instrukcja, ze trzeba przejsc przez auth.

To oznacza, ze na tym etapie warto dopiac tez brakujace u Ciebie mechanizmy:

- `waiting`
- `deliver`
- resume po dostarczeniu wyniku albo po zakonczeniu auth

Bez tego integracje user-scoped beda dzialac topornie.

### 2.5. Dodac confirmation flow dla operacji write

To jest szczegolnie wazne dla:

- kalendarza,
- maili,
- CRM,
- task managerow.

Rekomendowany model:

- tool `read` wykonuje sie od razu,
- tool `write` najpierw daje plan akcji,
- backend przechodzi do `waiting`,
- user potwierdza,
- dopiero wtedy runner wykonuje write przez MCP.

To spina sie naturalnie z juz planowanym u Ciebie mechanizmem human-in-the-loop.

### 2.6. Dodac audyt i observability MCP per user

Dla remote MCP potrzebny jest mocniejszy audyt niz dla `files-mcp`.

Minimalnie logowac:

- `user_id`
- `server`
- `tool`
- argument preview bez danych wrazliwych
- start i czas wykonania
- wynik `success/failure/auth_required/confirmation_required`

Przy `calendar__create_event` dobrze miec mozliwosc odpowiedzi na pytanie:

- kto uruchomil akcje,
- z jakiego agenta,
- kiedy,
- z jakim wynikiem.

### 2.7. Dodac katalog przykladowych integracji

Na poziomie docs warto przygotowac docelowo osobne playbooki:

- `docs/mcp_google_maps_plan.md`
- `docs/mcp_google_calendar_plan.md`

Bo te integracje beda sie roznic nie tyle technicznie transportem, co polityka bezpieczenstwa i UX.

## Jak to zastosowac do Google Maps i Google Calendar

### Google Maps

Najrozsadniejszy pierwszy wariant:

- tylko read-only,
- ownership `shared`,
- bez confirmation,
- uzycie do wyszukiwania miejsc, adresow, ETA, geocodingu.

Plan:

1. podpiac remote MCP `maps`
2. dodac polityki `read_only`
3. wystawic toole typu:
   - `maps__search_places`
   - `maps__get_place_details`
   - `maps__estimate_route`
4. pozwolic agentowi wykonywac je synchronicznie bez `waiting`

To jest dobry pierwszy remote MCP, bo nie zmienia stanu zewnetrznego systemu.

### Google Calendar

Najrozsadniejszy pierwszy wariant:

- ownership `user_scoped`,
- OAuth per user,
- osobne rozroznienie read vs write,
- confirmation dla create/update/delete.

Plan:

1. podpiac remote MCP `calendar`
2. dodac OAuth i storage tokenow
3. zaczac od tooli read:
   - `calendar__list_events`
   - `calendar__find_free_slots`
4. dopiero potem dolozyc write:
   - `calendar__create_event`
   - `calendar__update_event`
   - `calendar__delete_event`
5. write od razu spinac z confirmation flow

To jest bezpieczniejsza kolejnosc niz wrzucenie od razu pelnego CRUD.

## Proponowana kolejnosc zmian w repo

Najmniej ryzykowna kolejnosc PR-ow:

1. `app/mcp` + testy jednostkowe managera
2. DI i lifecycle aplikacji
3. integracja `AgentLoader`
4. integracja `Runner`
5. dokumentacja `.mcp.json` i przykladowy config
6. opcjonalnie endpointy `/api/v1/mcp/*`
7. modele `McpConnection` i storage tokenow
8. HTTP transport i statusy `auth_required`
9. OAuth callback flow per user
10. confirmation flow dla tooli write
11. pierwsze integracje remote: `maps` read-only, potem `calendar` read-only, na koncu `calendar` write

## Decyzje projektowe, ktore warto przyjac od razu

### 1. MCP nie wchodzi do bazy danych

Konfiguracja serwerow MCP powinna zostac plikowa i srodowiskowa.
To jest zgodne z charakterem tych polaczen i upraszcza deployment.

### 2. MCP nie rozszerza `ToolRegistry`

`ToolRegistry` juz dzis obsluguje tylko lokalne `Tool`.
MCP jest zewnetrznym zrodlem narzedzi i powinno zostac osobnym adapterem.

### 3. MVP ma wspierac tylko `files-mcp`

Nie ma sensu projektowac wszystkiego pod OAuth i HTTP, zanim agent nie umie czytac plikow przez `stdio`.
To jest najkrotsza droga do wartosci.

### 4. Output MCP normalizujemy do tekstu lub JSON string

Aktualny runner i itemy juz umieja przechowywac output jako string.
Nie warto teraz przebudowywac modelu danych tylko pod structured MCP output.

## Ryzyka i uwagi

- najwieksze ryzyko techniczne to lifecycle procesow `stdio` i ich poprawne zamykanie,
- drugie ryzyko to rozjazd katalogu roboczego pomiedzy aplikacja a serwerem MCP,
- trzecie ryzyko to zbyt szeroki dostep `files-mcp` do filesystemu; trzeba ograniczyc mounty,
- jesli `files-mcp` zostanie uruchamiany przez `node` lub `bun`, trzeba miec stabilny sposob zbudowania albo wskazania entrypointu.

## Definicja done dla MVP

MVP uznajemy za zakonczony, gdy:

1. `manfred` startuje z `.mcp.json` zawierajacym serwer `files`
2. agent z frontmatterem `files__fs_read` laduje sie poprawnie
3. provider moze zwrocic MCP function call
4. `Runner` wykona go przez `McpManager`
5. wynik zostanie zapisany jako `function_call_output`
6. agent wykorzysta ten wynik w kolejnej turze i odpowie uzytkownikowi

## Rekomendacja wdrozeniowa

Najrozsadniej wdrazac to w dwoch krokach:

1. MVP: `stdio + files-mcp + loader + runner + testy`
2. rozszerzenie: `HTTP + OAuth + endpointy statusowe`

Taki podzial jest spojny z obecnym stanem `manfreda` i minimalizuje ryzyko, ze projekt ugrzeznie na mniej potrzebnych elementach transportu HTTP zanim agent zacznie realnie korzystac z plikow.
