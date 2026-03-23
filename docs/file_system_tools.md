# Plan wdrożenia narzędzi `file_system` w `manfred`

## Cel

Wdrożyć w `manfred` natywny zestaw narzędzi plikowych inspirowany repo `files-stdio-mcp-server`, ale dopasowany do obecnej architektury Pythona:

- narzędzia mają żyć w `src/app/agent/tools/file_system/`
- każdy tool ma mieć osobny plik `.py`
- rejestracja ma dalej odbywać się centralnie przez `container.py`
- wynik ma korzystać z obecnego kontraktu `Tool` + `tool_ok` / `tool_error`, a nie z MCP `CallToolResult`

## Co warto przenieść ze źródłowego repo

Po analizie `files-stdio-mcp-server` najważniejsze elementy do przeniesienia to:

- `fs_read` z `src/tools/fs-read.tool.ts`
  - listing katalogów
  - odczyt pliku z numerami linii
  - checksum zwracany przy odczycie
  - filtrowanie po `glob`, `types`, `exclude`
- `fs_search` z `src/tools/fs-search.tool.ts`
  - search po nazwach plików
  - search po treści
  - tryby `literal`, `regex`, `fuzzy`
  - limity wyników i kontrola głębokości
- `fs_write` z `src/tools/fs-write.tool.ts`
  - `create` i `update`
  - update line-based: `replace`, `insert_before`, `insert_after`, `delete_lines`
  - `checksum` do ochrony przed stale write
  - `dryRun` i diff przed zapisem
- `fs_manage` z `src/tools/fs-manage.tool.ts`
  - `mkdir`, `stat`, `rename`, `move`, `copy`, `delete`

Do portu nadają się też helpery z:

- `src/lib/paths.ts`
- `src/lib/lines.ts`
- `src/lib/checksum.ts`
- `src/lib/diff.ts`
- `src/lib/file-search.ts`
- `src/lib/patterns.ts`

Nie ma sensu przenosić warstwy MCP, Zod ani bundli MCPB. W `manfred` potrzebna jest wyłącznie warstwa natywnych tooli.

## Stan obecny w `manfred`

Aktualny pakiet `src/app/agent/tools/files/` daje tylko podstawowe operacje:

- `read_file` czyta cały plik bez checksumów i bez numeracji linii
- `write_file` nadpisuje cały plik
- `search_files` robi prosty exact substring search po bajtach
- `list_files`, `create_directory`, `delete_file`, `file_info` są rozbite na małe, wąskie toole

Braki względem MCP:

- brak bezpiecznego workflow `read -> dryRun -> apply`
- brak line-based editów
- brak diffów
- brak ochrony checksumem
- brak jednego spójnego interfejsu dla operacji strukturalnych
- brak semantyki przyjaznej agentowi w opisach tooli

## Docelowa struktura

Rekomendowana struktura pakietu:

```text
src/app/agent/tools/file_system/
  __init__.py
  common.py
  checksum.py
  diff_utils.py
  line_ops.py
  path_guard.py
  text_utils.py
  ignore_rules.py
  search_index.py
  pattern_matching.py
  fs_read.py
  fs_search.py
  fs_write.py
  fs_manage.py
```

Uwagi:

- każdy publiczny tool siedzi w osobnym pliku: `fs_read.py`, `fs_search.py`, `fs_write.py`, `fs_manage.py`
- helpery mogą być współdzielone i powinny być małe
- `download_file` nie należy do tego zestawu i może zostać w starym pakiecie albo później zostać przeniesiony osobno

## Decyzje architektoniczne dla `manfred`

### 1. Nazwy tooli

Wprowadzić nowe nazwy dokładnie w stylu MCP:

- `fs_read`
- `fs_search`
- `fs_write`
- `fs_manage`

To jest lepsze niż rozbudowywanie obecnych `read_file` / `write_file`, bo:

- semantyka jest już sprawdzona w repo źródłowym
- łatwiej opisać agentowi poprawny workflow
- unikamy mieszania prostych i bezpiecznych operacji pod tymi samymi nazwami

### 2. Sandbox

V1 powinno działać na pojedynczym rootcie `WORKSPACE_ROOT` z `app/config.py`.

Decyzja:

- nie wprowadzać od razu multi-mount z `FS_ROOTS`
- zachować API gotowe do rozszerzenia, ale implementację oprzeć o pojedynczy workspace
- `fs_read(".")` powinno listować root workspace, a nie wirtualne mounty

To upraszcza wdrożenie i dobrze pasuje do obecnego modelu `manfred`.

### 3. Kontrakt odpowiedzi

Każdy tool ma zwracać obecny format `ToolResult`:

- sukces przez `tool_ok(...)`
- błąd przez `tool_error(...)`

Wewnątrz `output` warto zachować strukturę mocno zbliżoną do MCP, np.:

- `success`
- `path`
- `type`
- `content` / `entries`
- `hint`
- `error.code`

To pozwoli zachować ergonomię dla modelu bez przebudowy runtime.

### 4. Bezpieczeństwo

Minimalny zakres bezpieczeństwa w V1:

- tylko ścieżki względne względem `WORKSPACE_ROOT`
- blokada `..`
- blokada path escape po `resolve(strict=False)`
- zakaz pracy na absolute path
- walidacja symlinków tak, aby nie wychodziły poza workspace
- brak recursive delete w pierwszej wersji

Uwaga: w repo źródłowym jest niespójność między opisem `fs_manage` a testem integracyjnym dla recursive delete. W `manfred` lepiej przyjąć bardziej restrykcyjną wersję: brak recursive delete.

## Plan implementacji

### Etap 1. Przygotowanie wspólnych helperów

Stworzyć moduły:

- `common.py`
  - budowa `Tool`
  - wspólne błędy i `hint`
  - `display_path`
- `path_guard.py`
  - resolve ścieżki w obrębie workspace
  - walidacja symlinków
  - rozróżnienie file / directory / missing
- `checksum.py`
  - `sha256(...).hexdigest()[:12]`
- `diff_utils.py`
  - unified diff przez `difflib.unified_diff`
- `line_ops.py`
  - `parse_line_range`
  - `add_line_numbers`
  - `extract_lines`
  - `replace_lines`
  - `insert_before_line`
  - `insert_after_line`
  - `delete_lines`
- `text_utils.py`
  - wykrywanie plików tekstowych
  - normalizacja końca linii

Rekomendacja zależności:

- stdlib wystarczy dla `checksum`, `diff`, `line_ops`
- dodać `pathspec` do sensownej obsługi `.gitignore`
- opcjonalnie dodać `rapidfuzz` do lepszego filename search; jeśli chcesz minimalny zakres V1, można zacząć od substring + ranking własny

### Etap 2. `fs_read.py`

Zakres:

- odczyt pliku tekstowego
- numeracja linii
- zwracanie checksumu
- partial read przez `lines="10-50"`
- listowanie katalogu z `depth`, `limit`, `offset`
- filtrowanie po `types`, `glob`, `exclude`
- opcjonalne `details`

Ważne decyzje:

- zwracać line numbers tylko przy odczycie pliku
- dla katalogów zwracać spójne `entries`
- w V1 nie trzeba implementować multi-mount overview

### Etap 3. `fs_search.py`

Zakres:

- `target="filename" | "content" | "all"`
- `pattern_mode="literal" | "regex" | "fuzzy"`
- `case_insensitive`, `whole_word`, `multiline`
- `depth`, `max_results`, `types`, `glob`, `exclude`

Implementacja:

- filename search:
  - V1: substring + prosty ranking
  - V2 opcjonalnie: `rapidfuzz`
- content search:
  - tylko pliki tekstowe
  - wyniki z `path`, `line`, `text`
- zabezpieczenie regexów:
  - prosty guard na długość i oczywiste nested quantifiers, bez pełnego engine protection

### Etap 4. `fs_write.py`

Zakres:

- `operation="create" | "update"`
- create z `create_dirs=True`
- update line-based tylko dla plików tekstowych
- `action="replace" | "insert_before" | "insert_after" | "delete_lines"`
- `checksum`
- `dry_run`
- zwracanie unified diff

To jest najważniejszy etap, bo daje realnie bezpieczne edycje.

Kluczowe reguły:

- update wymaga `lines`
- dla akcji modyfikujących wymagany `content`
- checksum mismatch kończy się soft error
- plik po zapisie powinien kończyć się `\n`

### Etap 5. `fs_manage.py`

Zakres:

- `mkdir`
- `stat`
- `rename`
- `move`
- `copy`
- `delete`

Decyzje:

- `delete` tylko dla pliku albo pustego katalogu
- `rename` tylko w obrębie workspace
- `move` i `copy` mogą działać dla katalogów po jawnym `recursive=true`
- `force=true` tylko tam, gdzie nadpisanie jest faktycznie bezpieczne i czytelne

### Etap 6. Rejestracja i ekspozycja tooli

Zmiany:

- dodać `src/app/agent/tools/file_system/__init__.py`
- podmienić eksporty w `src/app/agent/tools/__init__.py`
- zaktualizować `container.py`, aby rejestrował nowe `filesystem_tools`

Rekomendacja migracyjna:

- przez krótki czas można zostawić stary pakiet `files/` w repo
- ale w aktywnej rejestracji narzędzi lepiej wystawić tylko nowe `fs_*`
- inaczej model będzie miał dwa konkurencyjne zestawy narzędzi do tego samego celu

### Etap 7. Prompt i instrukcje dla agenta

Zaktualizować `app/agent/prompts/system_prompt.md`, żeby model znał workflow:

1. `fs_read` albo `fs_search`
2. `fs_read` pliku przed edycją
3. `fs_write` z `dry_run=true`
4. `fs_write` z `dry_run=false` i `checksum`
5. `fs_manage` tylko do zmian strukturalnych

Bez tego nawet dobra implementacja będzie używana gorzej, niż powinna.

### Etap 8. Testy

Dodać osobne testy dla nowego pakietu, najlepiej rozbite na:

- `src/tests/test_fs_read_tool.py`
- `src/tests/test_fs_search_tool.py`
- `src/tests/test_fs_write_tool.py`
- `src/tests/test_fs_manage_tool.py`

Minimalne scenariusze:

- path traversal blocked
- odczyt pliku i checksum
- partial read po liniach
- line-based replace/insert/delete
- checksum mismatch
- dry run nie zapisuje zmian
- search po nazwie i treści
- delete pustego katalogu i blokada dla niepustego
- symlink escape blocked

## Kolejność wdrożenia

Proponowana kolejność prac:

1. helpery współdzielone
2. `fs_read`
3. `fs_write`
4. `fs_search`
5. `fs_manage`
6. rejestracja i prompt
7. testy i wyłączenie starego pakietu `files`

Powód:

- `fs_read` i `fs_write` tworzą główny bezpieczny workflow
- `fs_search` może korzystać z helperów filtrujących zbudowanych wcześniej
- `fs_manage` jest najmniej krytyczny dla pierwszego użycia przez agenta

## Zakres V1 i rzeczy odłożone

Do V1:

- pojedynczy workspace root
- checksum
- diff
- line-based edit
- directory listing
- filename + content search
- bezpieczne operacje strukturalne

Po V1:

- multi-mount
- cache indeksów plików jak w `file-search.ts`
- bogatsze pattern presets
- progress notifications
- auto-resolve błędnych ścieżek

## Kryteria akceptacji

Wdrożenie uznam za gotowe, gdy:

- w `src/app/agent/tools/file_system/` istnieją 4 publiczne toole, każdy w osobnym pliku
- agent widzi tylko nowy zestaw `fs_*`
- `fs_write` wspiera checksum i `dry_run`
- testy dla nowych tooli przechodzą
- stary pakiet `files` nie jest już potrzebny do podstawowej pracy na plikach

## Rekomendacja końcowa

Nie robiłbym 1:1 portu całego repo TypeScript. Najlepsza ścieżka dla `manfred` to:

- zachować semantykę 4 głównych tooli z MCP
- uprościć model mountów do pojedynczego `WORKSPACE_ROOT`
- dopasować odpowiedzi do obecnego `ToolRegistry`
- przenieść tylko te helpery, które wspierają bezpieczny workflow agenta

To da prawie cały zysk z `files-stdio-mcp-server`, ale bez dokładania niepotrzebnej warstwy MCP do backendu `manfred`.
