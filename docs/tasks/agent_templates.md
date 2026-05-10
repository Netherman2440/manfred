# Agent Templates — backend

## Cel

Zbudować pełen CRUD agentów ("templatek") opartych o file system użytkownika oraz API potrzebne kreatorowi we frontendzie. Dokument zastępuje sekcje 1 ("seed default agent"), 3 ("Agents API") i fragmenty schemy AgentTemplate z poprzedniego `agents-api-and-file-download.md`. Tematy nie-agentowe (download pliku, refaktor `AgentFilesystemService`) wydzielone do `download_file.md`.

Specyfikacja jest self-contained — nie wymaga zaglądania do repo frontendu ani do poprzedniej wersji.

---

## Decyzje architektoniczne

### File system jako jedyne źródło prawdy

Templatki agentów żyją wyłącznie w plikach `*.agent.md`. **Nie wprowadzamy** tabeli `agent_templates` w SQLite.

**Dlaczego**:
- Agenci mają tools `read_file` / `write_file` z dostępem do `agents/`, więc mogą tworzyć/modyfikować templatki innych agentów (use case "Manfred sam tworzy nowego sub-agenta")
- Dwa źródła prawdy (SQL + FS) z dwustronną synchronizacją to hot path na rozjazdy
- `AgentModel` w bazie pozostaje — tam żyje runtime instance agenta w sesji (depth, root_agent_id, status). To inna warstwa danych niż templatka

**Konsekwencje**:
- API jest cienką warstwą nad FS: list = scan katalogu, get = read pliku, post = write pliku, put = overwrite pliku
- Walidacja "name unique" = `path.exists()`, atomowo nie da się 100% (race condition między `exists()` i `write`), ale akceptujemy bo to single-user app
- Brak tagów, brak full-text search, brak owner permissions ponad poziom `user_workspace_key`

### Granularność per-user

Każdy user ma własny katalog `{fs_root}/{user_key}/agents/`. Brak globalnych templatek dzielonych między userami. Default agent jest seedowany do user-space przy `ensure_user_workspace` z `default_agents/` w repo.

### Identyfikacja agenta = `name`

Nazwa pliku/folderu agenta jest jednocześnie jego ID w API (`{name}.agent.md` w folderze `{name}/`). PUT nie zmienia name (URL = source of truth). Rename agenta = scope poza V1.

---

## Nowa struktura katalogów

### Per-agent folder

Każda templatka to folder w `{user_workspace}/agents/`:

```
{user_workspace}/
  agents/
    manfred/                          ← folder = name agenta
      manfred.agent.md                ← główny plik z frontmatter + system prompt
    researcher/
      researcher.agent.md
```

### Format `*.agent.md`

```markdown
---
name: manfred
model: openai/gpt-4o-mini
color: "#5EA1FF"
description: Główny asystent do pracy z kodem i zadaniami.
tools:
  - read_file
  - write_file
  - delegate
---

You are Manfred, a helpful AI assistant...
```

Pola frontmatter:
- `name` (required) — musi być zgodne z nazwą folderu i nazwą pliku przed `.agent.md`
- `model` (optional) — model id z OpenRouter; null => błąd (nie używamy `OPEN_ROUTER_LLM_MODEL`)
- `color` (optional) — hex `#RRGGBB`; używany przez UI do akcentu
- `description` (optional) — krótki opis pokazywany w listach
- `tools` (optional) — lista nazw tooli; dla MCP dozwolone w pełni kwalifikowane nazwy (`mcp__server__tool`)

System prompt to wszystko poniżej zamykającego `---`.

### Default agent

Repo trzyma seed:

```
manfred_backend/
  default_agents/
    manfred/
      manfred.agent.md
```

Migracja: obecny `default_agents/manfred.agent.md` → `default_agents/manfred/manfred.agent.md`. Zmiana frontmatter: dodać `color`, `description`.

**Uwaga**: `_agent_name_from_path` zwracał stem pliku `.agent.md`. Po zmianie struktury templatka jest w `agents/{name}/{name}.agent.md` — `AgentLoader` musi znać tę regułę.

---

## Zmiany w domenie i loaderze

### Rozszerzenie `AgentTemplate`

`src/app/services/agent_loader.py`:

```python
@dataclass(slots=True, frozen=True)
class AgentTemplate:
    agent_name: str
    model: str | None
    color: str | None              # ← NOWE
    description: str | None        # ← NOWE
    tools: list[str]
    system_prompt: str
    source_dir: Path               # ← NOWE; abs path do folderu agenta
```

`load_agent_template()` musi:
- Akceptować ścieżkę do **pliku** `.agent.md` (jak teraz) **albo** ścieżkę do **folderu** agenta (wtedy szuka pliku `{folder_name}.agent.md` w środku)
- Czytać `metadata.get("color")`, `metadata.get("description")`
- Zwracać `source_dir` = parent pliku `.agent.md`

### Nowa metoda `_agent_path_for_name`

```python
def _agent_path_for_name(self, agent_name: str) -> Path:
    return Path(self.workspace_path) / "agents" / agent_name / f"{agent_name}{AGENT_EXTENSION}"
```

Stara wersja (`agents/{name}.agent.md`) odpada — zmiana hard-cut, **migracji istniejących userów nie robimy** (single-user dev środowisko, akceptujemy że stare workspaces wymagają ręcznego ruchu).

### Nowy serwis: `AgentTemplateService`

`src/app/services/agent_template_service.py` (NOWY plik):

Pełny CRUD per user. Nazwa "Service" zamiast "Repository", bo bezpośrednio uderza w FS i robi walidację — nie jest cienkim DAO.

```python
@dataclass(frozen=True, slots=True)
class AgentTemplateSummary:
    name: str
    color: str | None
    description: str | None

@dataclass(frozen=True, slots=True)
class AgentTemplateDetail:
    name: str
    color: str | None
    description: str | None
    model: str | None
    system_prompt: str
    tools: list[str]

@dataclass(frozen=True, slots=True)
class AgentTemplateInput:
    name: str
    color: str | None
    description: str | None
    model: str | None
    tools: list[str]
    system_prompt: str


class AgentTemplateService:
    NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")

    def __init__(
        self,
        *,
        agent_loader: AgentLoader,
        workspace_layout_service: WorkspaceLayoutService,
    ) -> None: ...

    def list_templates(self, user: User) -> list[AgentTemplateSummary]: ...
    def get_template(self, user: User, name: str) -> AgentTemplateDetail | None: ...
    def create_template(self, user: User, payload: AgentTemplateInput) -> AgentTemplateDetail: ...
    def update_template(self, user: User, name: str, payload: AgentTemplateInput) -> AgentTemplateDetail: ...
    def delete_template(self, user: User, name: str) -> None: ...  # raises AgentTemplateHasSessions jeśli są sesje
```

Reguły kluczowych metod:

**`create_template`**:
1. Walidacja `name` przez `NAME_PATTERN` (lower-snake, 1–48 znaków, zaczyna się literą). Nazwa zarezerwowana lista: `[".", "..", "agents", "default"]` — odrzucamy.
2. Sprawdzenie konfliktu: jeśli folder `agents/{name}/` już istnieje → `AgentTemplateExists`.
3. Walidacja `tools` przeciw `tool_registry.list()` + lista MCP tooli (akceptujemy też nazwy MCP). Nieznane → `AgentTemplateInvalid`.
4. Walidacja `model` (opcjonalnie): jeśli nie null, musi być stringiem niepustym; pełna walidacja przeciw OpenRouter pomijamy (drift między listą a rzeczywistością — nie blokujemy zapisu).
5. Walidacja `color`: regex `^#[0-9A-Fa-f]{6}$` lub null.
6. `mkdir agents/{name}/`, zapis pliku `{name}.agent.md` z frontmatter zbudowanym deterministycznie (kolejność kluczy: `name, model, color, description, tools`).
7. Zwraca `AgentTemplateDetail` (re-load z dysku).

**`update_template`**:
1. Sprawdzenie istnienia: jeśli folder nie istnieje → `AgentTemplateNotFound`.
2. `payload.name` musi == name z URL. Jeśli różny → `AgentTemplateInvalid` ("rename not supported").
3. Te same walidacje co przy create (tools, color, model).
4. Atomowy zapis: write do `.tmp`, `os.replace` na właściwy plik. Jeśli walidacja pre-write upadnie, niczego nie tykamy.

**`delete_template`**:
1. Sprawdzenie istnienia: jeśli folder nie istnieje → `AgentTemplateNotFound`.
2. **Atomowa transakcja**:
   - Usuń folder `agents/{name}/` całkowicie (`shutil.rmtree`)
   - DELETE FROM agents WHERE agent_name = name (usunięcie wszystkich sesji i sub-agentów dla tego agenta)
3. Jeśli cokolwiek fail → rollback całej transakcji (folder zostaje, baza bez zmian).
4. Zwróć sukces (204 No Content).

### Frontmatter writer

Dodać helper w `agent_loader.py` (lub osobny plik `agent_frontmatter.py`):

```python
def render_agent_frontmatter(template: AgentTemplate) -> str:
    """Deterministyczny YAML-like writer kompatybilny z _parse_frontmatter."""
```

Wartości muszą być serializowane tak, żeby `_parse_frontmatter` je z powrotem przeczytał. Listy (`tools`) renderowane z prefiksem `  - `. Stringi z dwukropkami / hashami otoczone podwójnym cudzysłowem.

### Custom exceptions

```python
class AgentTemplateError(Exception): pass
class AgentTemplateNotFound(AgentTemplateError): pass
class AgentTemplateExists(AgentTemplateError): pass
class AgentTemplateInvalid(AgentTemplateError):
    def __init__(self, field: str, message: str): ...
```

Mapowanie do HTTP w routerze: `NotFound` → 404, `Exists` → 409, `Invalid` → 422.

---

## Seed default agenta przy `ensure_user_workspace`

`WorkspaceLayoutService.ensure_user_workspace` po stworzeniu folderów `agents/` itd. kopiuje folder `default_agents/{DEFAULT_AGENT_NAME}/` do `{user_workspace}/agents/{DEFAULT_AGENT_NAME}/`, jeśli jeszcze nie istnieje.

**Zmiany w `WorkspaceLayoutService.__init__`**:

```python
def __init__(
    self,
    *,
    repo_root: Path,
    workspace_path: str,
    agent_mount_names: list[str] | None = None,
    default_agent_source_dir: Path | None = None,   # ← NOWE
    default_agent_name: str = "manfred",             # ← NOWE
    files_dir_name: str = "files",
    attachments_dir_name: str = "attachments",
    plan_file_name: str = "plan.md",
) -> None: ...
```

**Logika seedu w `ensure_user_workspace`** (po `mkdir` mount-ów):

```python
if self.default_agent_source_dir and self.default_agent_source_dir.is_dir():
    target = layout.root / "agents" / self.default_agent_name
    if not target.exists():
        shutil.copytree(self.default_agent_source_dir, target)
```

**Zmiany w `config.py`**:

```python
DEFAULT_AGENT: str = "manfred"  # ← ZMIANA: teraz to NAZWA agenta, nie ścieżka
DEFAULT_AGENT_SOURCE_DIR: str = "default_agents/manfred"  # repo-relative path do seeda
```

`DEFAULT_AGENT` jako nazwa, nie ścieżka — to daje spójność z `agent_config.agent_name`. Wszystkie miejsca obecnie ładujące `settings.DEFAULT_AGENT` jako path zmienić na `agent_loader.load_agent_by_name(settings.DEFAULT_AGENT)`.

**Zmiany w `.env.EXAMPLE`**:
```env
DEFAULT_AGENT=manfred
DEFAULT_AGENT_SOURCE_DIR=default_agents/manfred
```

**Zmiany w `container.py`**:
```python
workspace_layout_service = providers.Singleton(
    build_workspace_layout_service,
    settings=settings,
    repo_root=repo_root,
    default_agent_source_dir=providers.Callable(
        lambda settings, repo_root: repo_root / settings.DEFAULT_AGENT_SOURCE_DIR,
        settings=settings, repo_root=repo_root,
    ),
    default_agent_name=settings.provided.DEFAULT_AGENT,
)
```

---

## Wybór root agenta przy chacie

### Rozszerzenie `ChatAgentConfigInput`

`src/app/api/v1/chat/schema.py`:

```python
class ChatAgentConfigInput(BaseModel):
    agent_name: str | None = None    # ← NOWE; nazwa templatki z user/agents/
    model: str | None = None         # override model z templatki
    task: str | None = None          # override task (jeśli będzie)
    tools: list[ChatToolDefinitionInput] | None = None  # override tools
    temperature: float | None = None
```

**Reguły fallbacku w `ChatService`**:
1. Jeśli `agent_config.agent_name` podany → `agent_loader.load_agent_by_name(agent_name)`.
2. Else → `agent_loader.load_agent_by_name(settings.DEFAULT_AGENT)`.
3. Jeśli load rzuci `FileNotFoundError` (templatka usunięta między submitami) → 404 `agent template not found`.
4. Override-y (`model`, `tools`, `temperature`) aplikowane po załadowaniu templatki — to override per-message, nie modyfikacja templatki.

### Zapis `agent_name` na sesji

Sesja od strony bazy (`AgentModel`) ma `agent_name` — pole już istnieje w domenie. Przy tworzeniu nowej sesji w `ChatService.start_session()` wpisujemy `agent_name` z templatki (depth=0). To pozwala potem filtrować `GET /agents/{name}/sessions` przez JOIN na agent_name.

Jeśli `agent_name` istnieje już w `AgentModel` (z poprzedniego doku), nic nie zmieniamy. Jeśli nie — dodać kolumnę przez Alembic migration.

### Filtrowanie sesji per agent

Dodać do `SessionRepository`:

```python
def list_by_user_and_agent_name(
    self,
    user_id: str,
    agent_name: str,
    *,
    limit: int = 50,
) -> list[Session]:
    """JOIN sessions ↔ agents WHERE agents.depth=0 AND agents.agent_name=:name AND sessions.user_id=:user_id"""
```

---

## API

### Schema (`api/v1/agents/schema.py`)

```python
class AgentSummarySchema(BaseModel):
    name: str
    color: str | None
    description: str | None

class AgentDetailSchema(BaseModel):
    name: str
    color: str | None
    description: str | None
    model: str | None
    system_prompt: str
    tools: list[str]

class AgentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=48)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    description: str | None = Field(default=None, max_length=500)
    model: str | None = None
    tools: list[str] = Field(default_factory=list)
    system_prompt: str = Field(default="", max_length=20000)

class AgentUpdateRequest(BaseModel):
    # Identyczne pola co create, ale name MUSI == path param.
    name: str
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    description: str | None = Field(default=None, max_length=500)
    model: str | None = None
    tools: list[str] = Field(default_factory=list)
    system_prompt: str = Field(default="", max_length=20000)

class AgentsListResponse(BaseModel):
    data: list[AgentSummarySchema]

class AgentDetailResponse(BaseModel):
    data: AgentDetailSchema

class AgentSessionsResponse(BaseModel):
    data: list[SessionListItemSchema]   # reuse z users/schema

class ToolSummarySchema(BaseModel):
    name: str
    description: str | None
    type: Literal["function", "web_search", "mcp"]

class ToolsListResponse(BaseModel):
    data: list[ToolSummarySchema]

class ModelSummarySchema(BaseModel):
    id: str               # np. "openai/gpt-4o-mini"
    name: str             # human-readable "GPT-4o mini"
    context_length: int | None
    pricing_prompt_per_1k: float | None
    pricing_completion_per_1k: float | None

class ModelsListResponse(BaseModel):
    data: list[ModelSummarySchema]
```

### Endpoints

```
GET  /api/v1/agents
  → 200 AgentsListResponse
  → Lista templatek aktualnego usera

GET  /api/v1/agents/{name}
  → 200 AgentDetailResponse
  → 404 jeśli templatka nie istnieje

POST /api/v1/agents
  Request: AgentCreateRequest
  → 201 AgentDetailResponse
  → 409 {"detail": "agent_already_exists", "name": "..."}
  → 422 jeśli walidacja name/color/tools

PUT  /api/v1/agents/{name}
  Request: AgentUpdateRequest (name == path)
  → 200 AgentDetailResponse
  → 404 jeśli templatka nie istnieje
  → 422 jeśli walidacja / mismatch name

DELETE /api/v1/agents/{name}
  → 204 No Content
  → 404 jeśli templatka nie istnieje
  → Kaskadowo usuwa: folder agenta + wszystkie sesje gdzie agent_name == name (depth=0 i sub-agenci)

GET  /api/v1/agents/{name}/sessions
  → 200 AgentSessionsResponse
  → Sesje gdzie root agent_name == name

GET  /api/v1/tools
  → 200 ToolsListResponse
  → Lista tooli dostępnych do wyboru przy tworzeniu agenta

GET  /api/v1/models
  → 200 ModelsListResponse
  → Cache TTL=1h, fallback na cached gdy OpenRouter offline
  → 503 jeśli brak cache i request do OpenRouter się wywali
```

Wszystkie endpointy poza `/tools` i `/models` wymagają autoryzowanego usera (analogicznie do `/users/api.py`). `/tools` i `/models` też — operują w kontekście aplikacji ale nie chcemy publicznych. Decyzja: same auth wrapper co reszta API.

### Router (`api/v1/agents/api.py`)

Standardowy FastAPI router z DI przez `Depends(Provide[Container.agent_template_service])`. Mapowanie wyjątków przez `@router.exception_handler` lub try/except w handlerze.

Pliki nowe:
```
src/app/api/v1/agents/
  __init__.py
  api.py
  schema.py
src/app/api/v1/tools/
  __init__.py
  api.py
  schema.py
src/app/api/v1/models/
  __init__.py
  api.py
  schema.py
```

Podpięcie w `api/v1/api.py`: trzy nowe `include_router`.

---

## `/api/v1/tools` — szczegóły

### Serwis: `ToolCatalogService`

`src/app/services/tool_catalog_service.py`:

```python
class ToolCatalogService:
    def __init__(self, *, tool_registry: ToolRegistry, mcp_manager: McpManager) -> None: ...

    def list_tools(self) -> list[ToolSummary]:
        """Zwraca wszystkie dostępne toole: function tools z registry + web_search + MCP."""
```

Logika:
1. Iteruj `tool_registry.list()`. Dla każdego `FunctionToolDefinition` → `ToolSummary(name, description, type="function")`.
2. Dodaj specjalny `ToolSummary(name="web_search", description="Search the web", type="web_search")`.
3. Iteruj `mcp_manager.list_tools()` (jeśli istnieje taka metoda; jeśli nie — sprawdzić jak `AgentLoader.resolve_tool_definitions` to robi i wzorować się). Każdy → `ToolSummary(name=mcp_tool.prefixed_name, description=mcp_tool.description, type="mcp")`.

Sortowanie deterministyczne: `(type, name)`, gdzie `function < web_search < mcp`.

### Wykorzystanie

`AgentTemplateService.create_template` waliduje `payload.tools` przeciw `tool_catalog_service.list_tools()` (set nazw). Wszystkie nieznane → 422.

---

## `/api/v1/models` — szczegóły

### OpenRouter API

```
GET https://openrouter.ai/api/v1/models
Authorization: Bearer {OPEN_ROUTER_API_KEY}
```

Zwraca `{"data": [{"id": "...", "name": "...", "context_length": 8192, "pricing": {"prompt": "0.0000005", "completion": "0.0000015"}, ...}, ...]}`.

**Format odpowiedzi do potwierdzenia w runtime** — kontrakt OpenRouter jest stabilny ale parser musi być defensywny: wszystkie pola opcjonalne poza `id`.

### Serwis: `ModelCatalogService`

`src/app/services/model_catalog_service.py`:

```python
class ModelCatalogService:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,   # singleton w container
        api_url: str,                     # settings.OPEN_ROUTER_URL
        api_key: str,                     # settings.OPEN_ROUTER_API_KEY
        cache_ttl_seconds: int = 3600,
    ) -> None: ...

    async def list_models(self) -> list[ModelSummary]:
        """Cache TTL=1h. Przy miss-cache GET /models.
        Jeśli OpenRouter rzuci, a cache pusty → raise ModelCatalogUnavailable."""
```

Cache strategy: trzymaj `(timestamp, list[ModelSummary])` w pamięci. Współbieżne calle podczas miss-cache → jeden request (asyncio.Lock).

Mapowanie:
- `id` ← `data[].id`
- `name` ← `data[].name` lub `data[].id` jako fallback
- `context_length` ← `data[].context_length`
- `pricing_prompt_per_1k` ← `float(data[].pricing.prompt) * 1000` (OpenRouter podaje per token)
- `pricing_completion_per_1k` ← analogicznie

Sortowanie: alfabetycznie po `id`.

### Filtr (opcjonalnie w przyszłości)

Na razie zwracamy całą listę (~hundred-ish modeli z OpenRouter). Frontend ma searchable dropdown — radzi sobie.

---

## DI — `container.py`

Dodać:

```python
agent_template_service = providers.Factory(
    AgentTemplateService,
    agent_loader=agent_loader,
    workspace_layout_service=workspace_layout_service,
)

tool_catalog_service = providers.Factory(
    ToolCatalogService,
    tool_registry=tool_registry,
    mcp_manager=mcp_manager,
)

model_catalog_service = providers.Singleton(
    ModelCatalogService,
    http_client=http_client,
    api_url=settings.provided.OPEN_ROUTER_URL,
    api_key=settings.provided.OPEN_ROUTER_API_KEY,
)
```

Singleton dla `model_catalog_service` żeby cache współdzielony. `agent_template_service` Factory bo trzyma user-context (user przekazywany do metod).

---

## Walidacja `name` — szczegóły

```python
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
RESERVED_NAMES = {"default", "agents", "shared", "skills", "workflows", "workspaces", "."}
```

- Wymuszamy lower-snake bez spacji, bo nazwa = nazwa folderu = path component
- Max 48 znaków — bezpieczna granica dla path length na wszystkich platformach
- Reserved set: koliduje z mountami albo zachowuje sens systemowy
- Frontend powinien echo'wać te same reguły (live walidacja + 422 jako safety net)

---

## Kolejność implementacji

1. **Refaktor struktury defaulta** — `default_agents/manfred.agent.md` → `default_agents/manfred/manfred.agent.md`. Aktualizacja frontmatter (color, description).
2. **AgentTemplate + AgentLoader** — dodać color/description/image_relative_path/source_dir, zmiana `_agent_path_for_name` na folder-based.
3. **Bug fix: seed** — `WorkspaceLayoutService.ensure_user_workspace` kopiuje folder default agenta.
4. **`ChatAgentConfigInput.agent_name`** — rozszerzenie schemy + fallback w `ChatService`.
5. **`AgentTemplateService`** — pełen CRUD bez image.
6. **Agents API** — list, get, post, put, sessions.
7. **`ToolCatalogService` + `/tools`**.
8. **`ModelCatalogService` + `/models`** (z cache).

Każdy krok można merge'ować osobno; krok 2 i 3 robić **razem** żeby nie zostawić workspace'ów w niespójnym stanie między merge'ami.

---

## Pliki do stworzenia / zmiany

| Plik | Akcja |
|------|-------|
| `default_agents/manfred/manfred.agent.md` | RENAME + edycja frontmatter |
| `default_agents/manfred.agent.md` | USUNĄĆ |
| `services/agent_loader.py` | Rozszerzenie AgentTemplate, zmiana `_agent_path_for_name`, akceptacja folder-path w `load_agent_template` |
| `services/agent_template_service.py` | NOWY |
| `services/tool_catalog_service.py` | NOWY |
| `services/model_catalog_service.py` | NOWY |
| `services/filesystem/workspace_layout.py` | Seed default agenta z folderu |
| `api/v1/agents/__init__.py` | NOWY |
| `api/v1/agents/api.py` | NOWY |
| `api/v1/agents/schema.py` | NOWY |
| `api/v1/tools/api.py` | NOWY |
| `api/v1/tools/schema.py` | NOWY |
| `api/v1/models/api.py` | NOWY |
| `api/v1/models/schema.py` | NOWY |
| `api/v1/api.py` | Podpiąć agents, tools, models |
| `api/v1/chat/schema.py` | Dodać `agent_name` do `ChatAgentConfigInput` |
| `services/chat_service.py` | Fallback agent_name → `load_agent_by_name` |
| `domain/repositories/session_repository.py` | `list_by_user_and_agent_name` (jeśli brak) |
| `config.py` | `DEFAULT_AGENT` semantyka, `DEFAULT_AGENT_SOURCE_DIR`, `MAX_AGENT_IMAGE_BYTES`, `API_BASE_URL` |
| `container.py` | Rejestracja 3 nowych serwisów + httpx client |
| `.env.EXAMPLE` | Aktualizacja zmiennych |

---

## Out of scope (V1)

- Rename agenta (zmiana name) — **V2 feature** (atomic rename folder + files + UPDATE agent_name w bazach)
- Globalne / shared templatki między userami
- Walidacja modelu przeciw rzeczywistej liście OpenRouter przy create/update
- Obsługa observational memory
- Wersjonowanie templatek / historia zmian
- Profile images agentów
