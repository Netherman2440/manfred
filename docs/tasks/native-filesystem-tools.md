# Plan backendu: native filesystem tools

## Cel backendowy

Backend ma przejac odpowiedzialnosc za filesystem tools, ktore dzis sa dostarczane przez zewnetrzny `files` MCP server. Docelowo agent ma miec ten sam zakres pracy na plikach, ale wykonanie ma byc lokalne, pythonowe i wpelni kontrolowane przez Manfreda.

To nie jest tylko przepiecie transportu z MCP na lokalny handler. Ten task ma dodac nowa warstwe backendowa:
- wspolny serwis filesystemu,
- centralna walidacje sciezek i mountow,
- jawna polityke dostepu per user / session / agent / tool,
- cienkie tool wrappery korzystajace z tej warstwy.

## Stan obecny

Obecny backend:
- ma generic MCP support w `src/app/mcp/`,
- ma `McpManager` podpiety w `src/app/container.py`,
- ma runtime umiejacy wykonac MCP tool call w `src/app/runtime/runner.py`,
- ma domyslny wpis `files` w `manfred_backend/.mcp.json`.

Aktualny config `manfred_backend/.mcp.json` wskazuje na serwer `files` ze zdefiniowanym `FS_ROOTS` dla:
- `.agent_data/agents`
- `.agent_data/shared`
- `.agent_data/skills`
- `.agent_data/workflows`
- `.agent_data/workspaces`

Najwazniejsze ograniczenie obecnej architektury lokalnych tooli:
- `ToolRegistry.execute(...)` i lokalne handlery dostaja tylko `args` i `signal`,
- nie ma jawnego `ToolExecutionContext`,
- przez to lokalny tool nie ma dostepu do `user_id`, `session_id` ani `agent_id`,
- bez tej zmiany nie da sie wiarygodnie egzekwowac polityki dostepu per user.

## Docelowy kontrakt funkcjonalny

Zakres ma pozostac rownowazny wobec `files-stdio-mcp-server`.

### Publiczne nazwy tooli

Rekomendacja: docelowe nazwy narzedzi to:
- `read_file`
- `search_file`
- `write_file`
- `manage_file`

Powod:
- nazwy sa prostsze i bardziej natywne dla lokalnych tooli,
- nazwy nie udaja juz prefiksowanego MCP servera,
- kontrakt tooli staje sie czytelniejszy po stronie backendu.

Konsekwencja:
- trzeba zaktualizowac agent definitions i ewentualne prompty, ktore dzis odwoluja sie do `files__*`.

### `read_file`

Ma zachowac semantyke:
- odczyt pliku,
- listowanie katalogu,
- root listing dla `"."`,
- obsluge mountow,
- `mode` typu `auto/tree/list/content`,
- `lines`, `depth`, `limit`, `offset`, `details`, `types`, `glob`, `exclude`, `respectIgnore`,
- checksum i line-numbered content dla plikow tekstowych.

### `search_file`

Ma zachowac:
- search po nazwie pliku i/lub tresci,
- `patternMode` typu `literal`, `regex`, `fuzzy`,
- `target` typu `all`, `filename`, `content`,
- `caseInsensitive`, `wholeWord`, `multiline`,
- `depth`, `types`, `glob`, `exclude`, `maxResults`, `respectIgnore`.

### `write_file`

Ma zachowac:
- `operation=create|update`,
- line-based targeting przez `lines`,
- `action=replace|insert_before|insert_after|delete_lines`,
- checksum verification,
- `dryRun=true` z diff preview,
- `createDirs`,
- odpowiedzi z `hint`, `error`, `diff`, `newChecksum`.

### `manage_file`

Ma zachowac:
- `operation=delete|rename|move|copy|mkdir|stat`,
- `target`, `recursive`, `force`,
- bezpieczne ograniczenia delete i walidacje source/target path.

## Docelowy kontrakt bezpieczenstwa

Filesystem ma miec dwa poziomy autoryzacji.

### Poziom 1: root sandbox

To jest statyczny limit systemowy:
- backend przyjmuje `FS_ROOTS` albo fallback `FS_ROOT`,
- wartosci sa mapowane do mountow i traktowane jako absolutna granica widocznosci,
- nic poza tymi rootami nie moze byc odczytane ani zmodyfikowane.

Ten poziom ma zachowac semantyke referencji:
- brak sciezek absolutnych,
- brak `..`,
- brak wyjscia poza mount,
- brak ucieczki przez symlink chain.

### Poziom 2: runtime access policy

To jest nowy element potrzebny Manfredowi.

Kazde wywolanie toola musi byc przepuszczone przez policy, ktora zna przynajmniej:
- `user_id`
- `session_id`
- `agent_id`
- `tool_name`
- `operation`
- `requested_path`
- opcjonalnie `target_path`

Przyklad docelowy:
- `FS_ROOTS` dopuszcza cale `.agent_data/workspaces`,
- ale `read_file` dla usera `u-1` moze wejsc tylko do `.agent_data/workspaces/u-1/`,
- sciezka innego usera jest odrzucana z bledem autoryzacji mimo tego, ze miesci sie w globalnym root.

## Rekomendowana architektura

### 1. `src/app/filesystem/`

Nowy pakiet aplikacyjny dla calej domeny filesystem tools.

Rekomendowany podzial:
- `src/app/filesystem/types.py`
- `src/app/filesystem/paths.py`
- `src/app/filesystem/policy.py`
- `src/app/filesystem/service.py`
- opcjonalnie `src/app/filesystem/search.py`
- opcjonalnie `src/app/filesystem/diff.py`

### 2. `types.py`

Trzyma modele wewnetrzne, np.:
- `FilesystemMount`
- `FilesystemSubject`
- `FilesystemAccessRequest`
- `FilesystemAccessDecision`
- `ResolvedFilesystemPath`
- modele odpowiedzi dla read/search/write/manage

Wazne: modele odpowiedzi nie musza byc identyczne klasowo do referencji, ale powinny dawac taki sam sensowny payload zwracany modelowi.

### 3. Konfiguracja w `src/app/config.py`

Odpowiada za:
- parse `FS_ROOTS` i fallback `FS_ROOT`,
- parse `FS_INCLUDE`,
- wartosci typu `MAX_FILE_SIZE`,
- ewentualne defaulty search/write.

Wymaganie repo:
- app code korzysta z `Settings`, nie z `os.environ`,
- dlatego `Settings` powinien byc jedynym kanonicznym miejscem dla tych zmiennych,
- nie dodajemy osobnego `src/app/filesystem/config.py`.

Rekomendacja:
- dodac potrzebne pola bezposrednio do `src/app/config.py`,
- utrzymac wsparcie dla env `FS_ROOTS` i fallback `FS_ROOT`,
- trzymac tam tez `MAX_FILE_SIZE` i `FS_INCLUDE`, jesli wejda do pierwszej wersji.

### 4. `paths.py`

To jest krytyczna warstwa bezpieczenstwa.

Ma implementowac:
- parse virtual path,
- rozwiazywanie mount name -> absolute root,
- rejection dla absolute paths,
- rejection dla `..`,
- kontrola `path.resolve()` w granicach mounta,
- walidacje symlinkow po calej sciezce.

Wlasnie tutaj warto przeniesc logike wzorowana na:
- `files-stdio-mcp-server/src/config/env.ts`
- `files-stdio-mcp-server/src/lib/paths.ts`

### 5. `policy.py`

To jest nowa warstwa specyficzna dla Manfreda.

Interfejs powinien byc prosty, np.:

```python
class FilesystemAccessPolicy(Protocol):
    async def authorize(self, request: FilesystemAccessRequest) -> FilesystemAccessDecision: ...
```

Minimalne cechy:
- decyzja `allow` / `deny`,
- kod bledu i message,
- mozliwosc podmiany implementacji w containerze,
- domyslna implementacja typu `AllowWithinConfiguredRootsPolicy`,
- mozliwosc zbudowania bardziej restrykcyjnej polityki per user workspace.

To wlasnie ta warstwa ma rozwiazywac Twoj przyklad:
- tool wie, kim jest user,
- path jest juz poprawny sandboxowo,
- policy decyduje, czy ten user moze uzyc tego konkretnego path.

### 6. `service.py`

Glowny `AgentFilesystemService` powinien byc jedynym miejscem wykonania read/search/write/manage.

Rekomendowany interfejs:

```python
class AgentFilesystemService:
    async def read(self, request: FilesystemReadRequest) -> FilesystemToolResult: ...
    async def search(self, request: FilesystemSearchRequest) -> FilesystemToolResult: ...
    async def write(self, request: FilesystemWriteRequest) -> FilesystemToolResult: ...
    async def manage(self, request: FilesystemManageRequest) -> FilesystemToolResult: ...
```

Serwis odpowiada za orkiestracje:
- walidacja input schema,
- path resolution,
- policy authorize,
- wykonanie operacji,
- serializacja do payloadu toola.

Tool wrapper nie powinien sam robic logiki plikowej poza minimalnym mapowaniem argumentow.

### 7. Tool wrappers

Zgodnie z konwencja repo:
- jeden tool = jeden plik,
- jesli to wspolny obszar, grupujemy je pod wspolnym katalogiem.

Rekomendowana struktura:
- `src/app/tools/definitions/filesystem/read_file.py`
- `src/app/tools/definitions/filesystem/search_file.py`
- `src/app/tools/definitions/filesystem/write_file.py`
- `src/app/tools/definitions/filesystem/manage_file.py`

Kazdy tool:
- definiuje JSON schema na gorze,
- pobiera `AgentFilesystemService` z DI,
- przekazuje `ToolExecutionContext`,
- zwraca `{"ok": True, "output": "<json-string>"}` albo `{"ok": False, "error": "..."}` zgodnie z obecnym kontraktem local tools.

## Niezbedna zmiana runtime

To jest najwazniejsza implikacja tego taska.

### Problem

Obecny `ToolHandler` ma podpis:

```python
Callable[[dict[str, Any], Any | None], Awaitable[ToolResult]]
```

W praktyce drugi argument jest wykorzystywany jako `signal`, a nie jako context wykonania.

### Rekomendacja

Dodac jawny `ToolExecutionContext`, np.:

```python
@dataclass(slots=True, frozen=True)
class ToolExecutionContext:
    user_id: str | None
    session_id: str
    agent_id: str
    call_id: str
    tool_name: str
    signal: CancellationSignal | None
```

I przeprowadzic zmiane:
- `domain/tool.py`
- `tools/registry.py`
- `runtime/runner.py`
- wszystkie istniejace lokalne toole, ktore moga ten context ignorowac

Minimalny wymog:
- `Runner` buduje context z danych `context.session`, `context.agent`, `function_call`,
- `ToolRegistry.execute(...)` przekazuje go do handlera,
- filesystem tools dostaja ten context explicite.

Ta zmiana jest in-scope, bo bez niej nie da sie zrealizowac programistycznych ograniczen per user.

## Integracja z DI i konfiguracja

Potrzebne zmiany w:
- `src/app/config.py`
- `src/app/container.py`
- `.env.EXAMPLE`
- `manfred_backend/README.md`

Container powinien budowac:
- filesystem settings/config,
- `FilesystemAccessPolicy`,
- `AgentFilesystemService`,
- liste lokalnych filesystem tools rejestrowanych w `ToolRegistry`.

Wazne:
- generic `McpManager` zostaje,
- ale filesystem nie powinien juz byc wymagany do runtime natywnych tooli,
- `manfred_backend/.mcp.json` zostaje w repo.

## Sugestia kolejnosci implementacji

### Etap 1. Kontrakt runtime dla local tools

Zakres:
- dodac `ToolExecutionContext`,
- zaktualizowac `ToolRegistry.execute(...)`,
- zaktualizowac `Runner`,
- utrzymac kompatybilnosc dotychczasowych local tools.

Kryterium akceptacji:
- istniejace toole nadal dzialaja,
- filesystem tool bedzie mogl odczytac `user_id`, `session_id`, `agent_id`.

### Etap 2. Konfiguracja i path security

Zakres:
- nowe fields w `Settings`,
- parse `FS_ROOTS` / `FS_ROOT`,
- path resolver i walidacja symlinkow,
- `FilesystemAccessPolicy`.

Kryterium akceptacji:
- sciezki absolutne i `..` sa odrzucane,
- root sandbox dziala niezaleznie od toola,
- policy potrafi zablokowac sciezke w ramach dozwolonego root-a.

### Etap 3. `read_file` i `search_file`

Zakres:
- read/list/tree/content,
- search po nazwie i tresci,
- search modes, globy, include/exclude,
- line numbers i checksum.

Kryterium akceptacji:
- agent moze eksplorowac workspace bez MCP,
- output jest czytelny i mozliwie bliski referencji.

### Etap 4. `write_file` i `manage_file`

Zakres:
- create/update/delete_lines/insert/replace,
- checksum mismatch,
- dryRun diff,
- rename/move/copy/mkdir/stat/delete.

Kryterium akceptacji:
- write path przechodzi przez te same warstwy walidacji i policy,
- destructive actions maja przewidywalne error messages i hints.

### Etap 5. Migracja setupu i testy

Zakres:
- usuniecie domyslnej zaleznosci runtime od zewnetrznego `files` MCP,
- aktualizacja README i `.env.EXAMPLE`,
- testy jednostkowe i integracyjne,
- aktualizacja agent docs i agent definitions, jesli gdziekolwiek opisujemy `files__*`.

Kryterium akceptacji:
- nowy developer uruchamia backend bez budowania `files-mcp`,
- filesystem dziala lokalnie,
- `.mcp.json` zostaje,
- MCP nadal dziala dla innych serwerow.

## Testy

### Jednostkowe

- `paths.py`: mount resolution, single/multi-root, absolute path reject, `..` reject
- symlink validation
- `policy.py`: allow/deny dla roznych userow, operacji i sciezek
- `fs_read`: checksum, lines, listing stats, root listing
- `fs_search`: filename/content, regex, fuzzy, truncation
- `fs_write`: checksum mismatch, dryRun, line range operations
- `fs_manage`: stat, mkdir, move/copy, delete safety

### Integracyjne

- `Runner` przekazuje `ToolExecutionContext`
- agent z `read_file` w definicji laduje sie jako local tool
- deny z `FilesystemAccessPolicy` wraca jako blad toola i nie wysypuje runtime

### Manualne

- user A czyta plik z wlasnego workspace
- user A probuje czytac plik usera B pod tym samym globalnym root-em i dostaje deny
- edycja z `dryRun=true`, potem `dryRun=false`
- proba `../../secret.txt`
- proba `/etc/passwd`

## In-scope / Out-of-scope

In-scope:
- lokalne filesystem toole,
- warstwa serwisowa,
- runtime context dla tooli,
- config i DI,
- parity z referencyjnym files MCP w zakresie text filesystem operations.

Out-of-scope:
- frontend UX dla filesystemu,
- osobne API endpoints do browse filesystemu,
- nowy system ACL w bazie danych, jesli nie jest niezbedny do pierwszej wersji,
- generalna likwidacja subsystemu MCP.

## Otwarte decyzje do zamkniecia przy implementacji

- Jak dokladnie modelujemy `FS_ROOTS` w `src/app/config.py`: pojedynczy string kompatybilny z env czy od razu pole znormalizowane do listy.
- Czy `respectIgnore` i `FS_INCLUDE` wchodza juz w pierwszym PR, czy po bazowej migracji read/search/write/manage.

Ustalone:
- `.mcp.json` zostaje w repo,
- konfiguracja filesystemu trafia bezposrednio do `src/app/config.py`.

## Handoff: planner

Done:
- opisano docelowa architekture serwisu filesystemu,
- ustalono, ze potrzebny jest `ToolExecutionContext`,
- ustalono docelowe nazwy tooli `read_file`, `search_file`, `write_file`, `manage_file`,
- ustalono dwuwarstwowy model autoryzacji: root sandbox + runtime policy.

Contract:
- backend ma odtworzyc zachowanie `files-stdio-mcp-server` jako lokalne toole,
- programistyczne ograniczenia per user musza byc wykonywane centralnie przez policy, nie ad hoc w pojedynczym helperze,
- filesystem tools nie moga zalezec od zewnetrznego procesu MCP.

Next role:
- `backend`

Risks:
- refactor kontraktu tool handlerow,
- spory zakres testow parity,
- potencjalne rozjazdy miedzy outputem referencji i obecnym oczekiwaniem modelu,
- koniecznosc aktualizacji agent definitions korzystajacych z `files__*`.
