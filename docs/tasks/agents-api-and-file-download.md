# Agents API & File Download

## Cel

Dostarczyć trzy niezależne kawałki funkcjonalności backendowej:

1. **Bug fix**: `ensure_user_workspace` nie tworzy domyślnego agenta — pierwsze uruchomienie z nowym userem kończy się błędem `FileNotFoundError`.
2. **Agents API**: endpointy do listowania i pobierania konfiguracji agentów z user-space (pliki `.agent.md`).
3. **File download endpoint**: możliwość pobrania pliku z workspace sesji przez HTTP — bez bazy danych, bez blob storage, tylko local filesystem.
4. **Filesystem service refactor**: wyciągnięcie klasy bazowej, zmiana nazwy, dodanie metody `download`.

Specyfikacja jest self-contained — nie wymaga zaglądania do repo frontendu.

---

## Kontekst lokalny

### Struktura katalogów

```
.agent_data/
  <user_key>/               ← tworzone przez ensure_user_workspace
    agents/                 ← pliki *.agent.md per user
    shared/
    skills/
    workflows/
    workspaces/
      <YYYY>/<MM>/<DD>/
        <session_id>/
          files/
          attachments/
          plan.md
```

Kluczowe pliki:
- `src/app/services/filesystem/workspace_layout.py` — `ensure_user_workspace` tworzy foldery, ale nie seeduje agentów
- `src/app/services/filesystem/service.py` — `AgentFilesystemService` (do refaktoru)
- `src/app/services/agent_loader.py` — `AgentLoader.load_agent_template()` parsuje frontmatter `.agent.md`
- `src/app/config.py` — `DEFAULT_AGENT`, `WORKSPACE_PATH`, `FS_MOUNTS`
- `src/app/container.py` — DI, tu rejestrujemy nowe serwisy/routery
- `src/app/api/v1/api.py` — tu podpinamy nowe routery

### Format pliku agenta

```markdown
---
name: Manfred
model: openai/gpt-4o-mini
color: "#5EA1FF"
description: Główny asystent do pracy z kodem i zadaniami.
tools:
  - read_file
  - write_file
---

System prompt agenta...
```

Frontmatter parsowany przez `AgentLoader._split_frontmatter()` i `_parse_frontmatter()`.
`AgentLoader.load_agent_template()` zwraca `AgentTemplate(agent_name, model, tools, system_prompt)`.

### Sesje a agent name

`SessionModel` ma `root_agent_id` (FK do `AgentModel.id`).
`AgentModel` ma `agent_name` (String, nullable) i `depth` — root agenci mają `depth=0`.
`SessionRepository.list_by_user()` istnieje. Brak metody filtrowania po `agent_name`.

---

## Scope

**In-scope:**
- Bug fix: seed domyślnego agenta przy `ensure_user_workspace`
- `GET /api/v1/agents` — lista agentów usera (metadane z frontmatter)
- `GET /api/v1/agents/{name}` — pełna konfiguracja agenta
- `GET /api/v1/agents/{name}/sessions` — sesje, gdzie root agent ma podane `agent_name`
- `GET /api/v1/sessions/{session_id}/files/download?path=<virtual_path>` — pobranie pliku
- Refaktor `AgentFilesystemService`: klasa bazowa `base.py`, zmiana nazwy na `local_service.py`, metoda `download()`

**Out-of-scope:**
- Tworzenie/edycja/usuwanie agentów przez API
- Upload plików
- Paginacja (na razie: max 100 agentów, max 50 sesji)
- Baza danych dla plików / blob storage
- AI attachment tool (oddzielny task)

---

## 1. Bug fix — seed domyślnego agenta

### Problem

`ensure_user_workspace` tworzy foldery `agents/`, `shared/`, itd., ale nie kopiuje żadnego agenta startowego. Pierwsze `load_agent(settings.DEFAULT_AGENT)` wywołane przy `chat/completions` szuka pliku, którego nie ma.

### Rozwiązanie

Dodać do `WorkspaceLayoutService.ensure_user_workspace()` opcjonalne seedowanie pliku agenta.

**Nowy parametr w `WorkspaceLayoutService.__init__`:**
```python
default_agent_source: Path | None = None  # abs path do pliku źródłowego
default_agent_name: str = "manfred.agent.md"  # nazwa w docelowym agents/
```

**Logika w `ensure_user_workspace`:**
```python
agents_dir = layout.root / "agents"
if default_agent_source and default_agent_source.exists():
    target = agents_dir / default_agent_name
    if not target.exists():
        shutil.copy2(default_agent_source, target)
```

**W `config.py` — nowe pole:**
```python
DEFAULT_AGENT_TEMPLATE: str = "default_agents/manfred.agent.md"
```

**W `container.py`** — przekazać `default_agent_source` do `WorkspaceLayoutService`:
```python
default_agent_source=repo_root / settings.DEFAULT_AGENT_TEMPLATE,
default_agent_name=Path(settings.DEFAULT_AGENT_TEMPLATE).name,
```

**Zmiana `DEFAULT_AGENT` w configu:**
Obecny default `DEFAULT_AGENT: str = "default_agents/manfred.agent.md"` powinien zostać zachowany — jest używany przez `chat_service` jako fallback gdy frontend nie poda `agent_config`.
Nowe pole `DEFAULT_AGENT_TEMPLATE` wskazuje plik źródłowy do seedowania.

**W `.env.EXAMPLE`:**
```env
DEFAULT_AGENT_TEMPLATE=default_agents/manfred.agent.md
```

---

## 2. Filesystem service refactor

### Cel

`AgentFilesystemService` nie ma abstrakcji — jest one-liner do LocalFS. Przygotujemy fundament pod przyszłe implementacje (S3, GCS) bez nadmiernego over-engineering.

### Zmiany plików

```
src/app/services/filesystem/
  base.py           ← NOWY: abstrakcyjna klasa bazowa
  local_service.py  ← RENAME z service.py
  service.py        ← USUNIETE (lub re-export dla kompatybilności, do decyzji)
  __init__.py       ← zaktualizować importy
```

**`base.py`** — abstrakcyjna klasa:
```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

class AbstractFilesystemService(ABC):
    @abstractmethod
    async def read(self, request) -> dict[str, Any]: ...
    @abstractmethod
    async def search(self, request) -> dict[str, Any]: ...
    @abstractmethod
    async def write(self, request) -> dict[str, Any]: ...
    @abstractmethod
    async def manage(self, request) -> dict[str, Any]: ...
    @abstractmethod
    def download(self, virtual_path: str) -> tuple[Path, str]:
        """Returns (absolute_path, media_type). Raises FilesystemToolError if not accessible."""
        ...
    @abstractmethod
    def list_mounts(self) -> list: ...
    @abstractmethod
    def generate_filesystem_instructions(self) -> str: ...
```

**`local_service.py`** — `AgentFilesystemService` dziedziczy z `AbstractFilesystemService`.

**Nowa metoda `download` w `AgentFilesystemService`:**
```python
def download(self, virtual_path: str) -> tuple[Path, str]:
    normalized = self.path_resolver.normalize_virtual_path(virtual_path)
    resolved = self.path_resolver.resolve(normalized)
    # sprawdzamy że jest w dozwolonym mount (synchronicznie, bez subject/tool_name)
    effective_path = resolved.absolute_path
    if not effective_path.exists() or not effective_path.is_file():
        raise FilesystemToolError(f"File not found: {virtual_path}")
    media_type = self._guess_media_type(effective_path)
    return effective_path, media_type

@staticmethod
def _guess_media_type(path: Path) -> str:
    import mimetypes
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"
```

**Wszystkie importy w kontenerze i narzędziach** — zaktualizować na `local_service.py`.

---

## 3. Agents API

### Nowe pliki

```
src/app/api/v1/agents/
  __init__.py
  api.py      ← router
  schema.py   ← Pydantic models
src/app/services/
  agent_config_service.py   ← logika czytania .agent.md per user
```

### `AgentConfigService`

Serwis czytający pliki `.agent.md` z katalogu `agents/` danego usera.

```python
class AgentConfigService:
    def __init__(self, *, agent_loader: AgentLoader, workspace_layout_service: WorkspaceLayoutService) -> None: ...

    def list_agents(self, user: User) -> list[AgentSummary]:
        """Skanuje <user_workspace>/agents/*.agent.md, parsuje frontmatter."""
        agents_dir = self._user_agents_dir(user)
        result = []
        for path in sorted(agents_dir.glob("*.agent.md")):
            try:
                tpl = self.agent_loader.load_agent_template(path)
                result.append(AgentSummary(
                    name=tpl.agent_name,
                    color=tpl.color,        # nowe pole w AgentTemplate
                    description=tpl.description,  # nowe pole
                ))
            except Exception:
                continue
        return result

    def get_agent(self, user: User, name: str) -> AgentDetail | None:
        """Zwraca pełne dane agenta."""
        path = self._user_agents_dir(user) / f"{name}.agent.md"
        if not path.exists():
            return None
        tpl = self.agent_loader.load_agent_template(path)
        return AgentDetail(
            name=tpl.agent_name,
            color=tpl.color,
            description=tpl.description,
            model=tpl.model,
            system_prompt=tpl.system_prompt,
            tools=tpl.tools,
        )

    def _user_agents_dir(self, user: User) -> Path:
        layout = self.workspace_layout_service.resolve_user_workspace(
            user_id=user.id, user_name=user.name
        )
        return layout.root / "agents"
```

### Rozszerzenie `AgentTemplate`

Dodać pola do `AgentTemplate` i `AgentLoader.load_agent_template()`:
```python
@dataclass(slots=True, frozen=True)
class AgentTemplate:
    agent_name: str
    model: str | None
    color: str | None      # ← NOWE z frontmatter "color:"
    description: str | None  # ← NOWE z frontmatter "description:"
    tools: list[str]
    system_prompt: str
```

Parsowanie w `_parse_frontmatter` już obsługuje dowolne klucze — wystarczy odczytać `metadata.get("color")` i `metadata.get("description")`.

### Schema (`schema.py`)

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

class AgentsListResponse(BaseModel):
    data: list[AgentSummarySchema]

class AgentDetailResponse(BaseModel):
    data: AgentDetailSchema

class AgentSessionsResponse(BaseModel):
    data: list[SessionListItemSchema]  # reużyć istniejącego schematu z users/schema.py
```

### Router (`api.py`)

Wszystkie endpointy wymagają `user_id` z kontekstu (analogicznie do `users/api.py`).

```
GET /api/v1/agents
  → 200: AgentsListResponse
  → Deleguje do AgentConfigService.list_agents(user)

GET /api/v1/agents/{name}
  → 200: AgentDetailResponse
  → 404: jeśli plik nie istnieje
  → Deleguje do AgentConfigService.get_agent(user, name)

GET /api/v1/agents/{name}/sessions
  → 200: AgentSessionsResponse
  → Filtruje sesje po root agent_name == name (depth=0 w AgentModel)
  → Deleguje do SessionQueryService lub bezpośrednio SessionRepository
```

### Filtrowanie sesji po agent name

Dodać do `SessionRepository` (lub `SessionQueryService`):
```python
def list_by_user_and_agent_name(self, user_id: str, agent_name: str) -> list[Session]:
    # JOIN sessions → agents WHERE agents.depth=0 AND agents.agent_name=:name
```

Alternatywnie — odfiltrować po stronie Python jeśli liczba sesji jest mała. Dla teraz: SQL join jest czystszy.

### DI w `container.py`

```python
agent_config_service = providers.Factory(
    AgentConfigService,
    agent_loader=agent_loader,
    workspace_layout_service=workspace_layout_service,
)
```

Router `agents/api.py` podpiąć w `api/v1/api.py`.

---

## 4. File Download Endpoint

### Endpoint

```
GET /api/v1/sessions/{session_id}/files/download
Query param: path=<virtual_path>   # np. workspace/files/raport.pdf
```

**Uwagi:**
- `virtual_path` to ścieżka wirtualna identyczna z tym co agent widzi (np. `workspace/files/raport.pdf`)
- Backend rozwiązuje ją przez `AgentFilesystemService.download(virtual_path)` skonfigurowany dla danej sesji
- Zwraca `FileResponse` z FastAPI (streaming, Content-Disposition: attachment)
- Autoryzacja: tylko właściciel sesji może pobrać plik — sprawdzamy `session.user_id == current_user.id`

### Implementacja

Nowy endpoint w `chat/api.py` (lub nowy router `sessions/api.py`):

```python
@router.get("/sessions/{session_id}/files/download")
@inject
async def download_session_file(
    session_id: str,
    path: str = Query(..., min_length=1),
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> FileResponse:
    try:
        absolute_path, media_type = await chat_service.get_session_file(
            session_id=session_id,
            virtual_path=path,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        path=absolute_path,
        media_type=media_type,
        filename=absolute_path.name,
    )
```

**`ChatService.get_session_file()`:**
```python
async def get_session_file(self, session_id: str, virtual_path: str) -> tuple[Path, str]:
    session = self.session_repository.get(session_id)
    if session is None or session.user_id != self.current_user.id:
        raise PermissionError()
    fs_service = self._build_filesystem_service_for_session(session)
    return fs_service.download(virtual_path)
```

`_build_filesystem_service_for_session` — metoda pomocnicza, która buduje `AgentFilesystemService` z odpowiednimi mountami dla sesji (analogicznie do tego co robi teraz `Runner` przed startem).

### Security

- Nie przyjmować ścieżek absolutnych ani `..` — `normalize_virtual_path` już to obsługuje
- Sprawdzać że resolved path jest pod allowlisted mountem (logika już w `FilesystemPathResolver`)
- Nie logować zawartości pliku

---

## Kolejność implementacji

1. **Filesystem refactor** (niezależny, bez efektów ubocznych)
2. **Bug fix** (szybki, odblokuje dalsze testy)
3. **Agent API** (AgentTemplate rozszerzenie → AgentConfigService → router)
4. **Download endpoint** (zależy od filesystem refactor)

---

## Pliki do stworzenia/zmiany

| Plik | Akcja |
|------|-------|
| `services/filesystem/base.py` | NOWY |
| `services/filesystem/local_service.py` | RENAME z service.py + dodanie download() |
| `services/filesystem/service.py` | USUNĄĆ lub zachować jako re-export |
| `services/filesystem/__init__.py` | Zaktualizować importy |
| `services/filesystem/workspace_layout.py` | Dodać seed agenta |
| `services/agent_loader.py` | Dodać color, description do AgentTemplate |
| `services/agent_config_service.py` | NOWY |
| `api/v1/agents/__init__.py` | NOWY |
| `api/v1/agents/api.py` | NOWY |
| `api/v1/agents/schema.py` | NOWY |
| `api/v1/api.py` | Podpiąć agents router |
| `api/v1/chat/api.py` | Dodać download endpoint (lub nowy router) |
| `domain/repositories/session_repository.py` | Dodać list_by_user_and_agent_name |
| `config.py` | Dodać DEFAULT_AGENT_TEMPLATE |
| `container.py` | Zarejestrować AgentConfigService, zaktualizować workspace layout |
| `.env.EXAMPLE` | Dodać DEFAULT_AGENT_TEMPLATE |
