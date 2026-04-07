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

- wzorzec architektoniczny: `/home/netherman/code/4th-devs/01_05_agent/src/mcp/client.ts`
- integracja z loaderem agenta: `/home/netherman/code/4th-devs/01_05_agent/src/workspace/loader.ts`
- wykonanie MCP tooli w petli: `/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts`
- obecny loader agenta w Pythonie: `/home/netherman/code/manfred/src/app/services/agent_loader.py`
- obecny runner w Pythonie: `/home/netherman/code/manfred/src/app/runtime/runner.py`
- obecny kontener DI: `/home/netherman/code/manfred/src/app/container.py`

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
        "/home/netherman/code/4th-devs/mcp/files-mcp/dist/index.js"
      ],
      "env": {
        "FS_ROOTS": "/home/netherman/code/manfred/.agent_data,/home/netherman/code/manfred/docs"
      },
      "cwd": "/home/netherman/code/manfred"
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

- `/home/netherman/code/manfred/src/app/mcp/__init__.py`
- `/home/netherman/code/manfred/src/app/mcp/types.py`
- `/home/netherman/code/manfred/src/app/mcp/config.py`
- `/home/netherman/code/manfred/src/app/mcp/client.py`

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

- dodac provider lub singleton MCP do `/home/netherman/code/manfred/src/app/container.py`,
- dodac ustawienie typu `MCP_CONFIG_PATH` albo wyprowadzic sciezke z root repo,
- wpiac `close()` w lifecycle aplikacji w `/home/netherman/code/manfred/src/app/main.py`.

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

## Proponowana kolejnosc zmian w repo

Najmniej ryzykowna kolejnosc PR-ow:

1. `app/mcp` + testy jednostkowe managera
2. DI i lifecycle aplikacji
3. integracja `AgentLoader`
4. integracja `Runner`
5. dokumentacja `.mcp.json` i przykladowy config
6. opcjonalnie endpointy `/api/v1/mcp/*`

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
