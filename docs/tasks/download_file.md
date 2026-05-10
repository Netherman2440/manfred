# File Download — backend

## Cel

Wystawić możliwość pobrania pliku z workspace sesji przez HTTP. Bez bazy danych, bez blob storage — tylko local filesystem przez `AgentFilesystemService`. Plus refaktor `AgentFilesystemService` pod abstrakcję bazową, żeby przyszłe S3/GCS implementacje miały gdzie się wpiąć.

Dokument wyciąga sekcje 2 ("filesystem refactor") i 4 ("download endpoint") z poprzedniego `agents-api-and-file-download.md`. Tematy agentowe (CRUD agentów, agents API) są w `agent_templates.md`.

Specyfikacja jest self-contained — nie wymaga zaglądania do repo frontendu.

---

## Scope

**In-scope:**
- Refaktor `AgentFilesystemService`: wyciągnięcie klasy bazowej, zmiana nazwy pliku
- Metoda `download(virtual_path) → (abs_path, media_type)` na serwisie filesystem
- Endpoint `GET /api/v1/sessions/{session_id}/files/download?path=<virtual_path>`
- `ChatService.get_session_file()` jako warstwa biznesowa (autoryzacja + budowa fs service per sesja)

**Out-of-scope:**
- Upload plików przez API (osobny task)
- Streaming dużych plików > 100 MB (FileResponse FastAPI radzi sobie do tej wielkości)
- Range requests (HTTP 206) — przeglądarki same dadzą radę dla typowych plików
- Walidacja content-type (zwracamy zgadnięty mime z `mimetypes`, frontend ufa)
- Pre-signed URLs (single-user app, prosta auth wystarczy)
- Delete pliku przez API (agent ma `manage_file` tool)

---

## 1. Filesystem service refactor

### Cel refaktoru

`AgentFilesystemService` to dziś jedyna implementacja, twardo wczepiona w lokalny FS. Wprowadzamy abstrakcję żeby:
- Móc wpiąć S3/GCS w przyszłości bez touch'owania `Runner`/`tools`
- Mieć jasny kontrakt operacji (read, write, search, manage, **download**)
- Nie over-engineerować — interfejs minimalny, żadnych Factory-of-Factories

### Struktura plików

```
src/app/services/filesystem/
  base.py            ← NOWY: AbstractFilesystemService
  local_service.py   ← NOWY (z RENAME service.py)
  service.py         ← USUNIĘTE (lub thin re-export — patrz niżej)
  paths.py           ← bez zmian
  policy.py          ← bez zmian
  types.py           ← bez zmian
  workspace_layout.py ← bez zmian (zmiany związane z agentami w innym docu)
  __init__.py        ← zaktualizować eksporty
```

### `base.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.services.filesystem.types import (
    FilesystemManageRequest,
    FilesystemReadRequest,
    FilesystemSearchRequest,
    FilesystemWriteRequest,
)


class AbstractFilesystemService(ABC):
    """Kontrakt na warstwę dostępu do plików.

    Trzy grupy operacji:
    - Async tool ops (read/search/write/manage) — używane przez agenta przez toole
    - Sync HTTP ops (download) — używane przez API
    - Introspekcja (list_mounts, generate_filesystem_instructions)
    """

    @abstractmethod
    async def read(self, request: FilesystemReadRequest) -> dict[str, Any]: ...

    @abstractmethod
    async def search(self, request: FilesystemSearchRequest) -> dict[str, Any]: ...

    @abstractmethod
    async def write(self, request: FilesystemWriteRequest) -> dict[str, Any]: ...

    @abstractmethod
    async def manage(self, request: FilesystemManageRequest) -> dict[str, Any]: ...

    @abstractmethod
    def download(self, virtual_path: str) -> tuple[Path, str]:
        """Resolwuje virtual_path do absolutnej ścieżki dla HTTP download.

        Returns:
            (absolute_path, media_type) — gotowe pod FileResponse.

        Raises:
            FilesystemToolError — jeśli ścieżka nieprawidłowa, poza dozwolonymi
                mountami, plik nie istnieje lub jest katalogiem.
        """
        ...

    @abstractmethod
    def list_mounts(self) -> list: ...

    @abstractmethod
    def generate_filesystem_instructions(self) -> str: ...
```

**Uwaga**: `download` jest **synchroniczny** (nie async) — to czysto path resolution + sprawdzenie istnienia. Stream samego pliku robi już FastAPI w warstwie HTTP (`FileResponse`).

**Uwaga**: `download` **nie** używa `access_policy` ani `subject` jak read/write. Powód: kontekst HTTP (current user) różni się semantycznie od kontekstu agenta (subject = agent name). Autoryzację robimy o jeden poziom wyżej — w `ChatService.get_session_file` sprawdzamy `session.user_id == current_user.id` i to wystarczy. `download` zatem broni się jedynie przed traversal (path normalization w `path_resolver`).

### `local_service.py`

`AgentFilesystemService` przeniesiona z `service.py`. Dodaje:

```python
class AgentFilesystemService(AbstractFilesystemService):
    # ... istniejący init, read, search, write, manage ...

    def download(self, virtual_path: str) -> tuple[Path, str]:
        normalized = self.path_resolver.normalize_virtual_path(virtual_path)
        if normalized in {".", ""}:
            raise FilesystemToolError("Cannot download root directory.")

        resolved = self.path_resolver.resolve(normalized)
        # resolved.absolute_path jest już ograniczone do mountów (path_resolver to robi)

        absolute_path = resolved.absolute_path
        if not absolute_path.exists():
            raise FilesystemToolError(f"File not found: {virtual_path}")
        if not absolute_path.is_file():
            raise FilesystemToolError(f"Path is not a file: {virtual_path}")
        if self._is_excluded_path(normalized, absolute_path.name):
            raise FilesystemToolError(f"Path '{virtual_path}' is excluded by filesystem policy.")
        if absolute_path.stat().st_size > self.max_file_size:
            raise FilesystemToolError(
                f"File '{virtual_path}' exceeds MAX_FILE_SIZE ({self.max_file_size} bytes)."
            )

        media_type = self._guess_media_type(absolute_path)
        return absolute_path, media_type

    @staticmethod
    def _guess_media_type(path: Path) -> str:
        import mimetypes
        mime, _ = mimetypes.guess_type(str(path))
        return mime or "application/octet-stream"
```

Dlaczego `max_file_size`: cap na pamięć/czas po stronie HTTP. Tych samych `MAX_FILE_SIZE` używają już read/write — spójnie. Frontend dostanie 413/400 w razie czego (mapping w endpointzie).

### `service.py` decyzja

Usunięty. Wszystkie importy idą do `local_service.py`. Jeśli istnieją zewnętrzne miejsca importujące `from app.services.filesystem.service import AgentFilesystemService`, pełna lista po:

```bash
rg "from app.services.filesystem.service" src/
rg "from app.services.filesystem import" src/
```

Wszystkie zmienić na `from app.services.filesystem.local_service import AgentFilesystemService`. Re-export w `__init__.py`:

```python
# src/app/services/filesystem/__init__.py
from app.services.filesystem.base import AbstractFilesystemService
from app.services.filesystem.local_service import AgentFilesystemService

__all__ = ["AbstractFilesystemService", "AgentFilesystemService"]
```

Powyższe re-exporty pozwalają importować z `app.services.filesystem` bez znajomości internalnej ścieżki — to jest publiczny API tego modułu.

### Container

W `container.py` zamienić import:

```python
# było:
from app.services.filesystem.service import AgentFilesystemService
# będzie:
from app.services.filesystem import AgentFilesystemService
```

`build_filesystem_service` factory zostaje bez zmian — nadal zwraca `AgentFilesystemService`. Type hint w callsites można podnieść do `AbstractFilesystemService` tam gdzie konsumenci używają tylko interfejsu (Runner, tools), ale to czysto kosmetyka, nie wymóg.

---

## 2. Download endpoint

### Lokalizacja

Endpoint trafia do **istniejącego `chat/api.py`**, nie tworzymy osobnego routera dla sesji. Powód: pozostałe operacje per-session (`/sessions/{id}/...`) już tam są, np. SSE stream, deliver. Zachowujemy spójność.

Alternatywnie, jeśli `chat/api.py` puchnie, można wydzielić `api/v1/sessions/api.py` w osobnym kroku — to czysto refaktor, nie wymóg tego doc-u.

### Schema (`chat/schema.py`)

Nie potrzebujemy DTO — endpoint zwraca binary. Wystarczy importować `FileResponse` z FastAPI.

### Endpoint

```python
from fastapi import HTTPException, Query
from fastapi.responses import FileResponse


@router.get("/sessions/{session_id}/files/download")
@inject
async def download_session_file(
    session_id: str,
    path: str = Query(..., min_length=1, description="Virtual path within session workspace"),
    user: User = Depends(get_current_user),                # auth dependency (jak w innych endpointach)
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
) -> FileResponse:
    try:
        absolute_path, media_type = await chat_service.get_session_file(
            session_id=session_id,
            virtual_path=path,
            user=user,
        )
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="session_not_found")
    except SessionAccessDeniedError:
        raise HTTPException(status_code=403, detail="session_access_denied")
    except FilesystemToolError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return FileResponse(
        path=absolute_path,
        media_type=media_type,
        filename=absolute_path.name,
    )
```

`Content-Disposition: attachment; filename="..."` jest dodawany automatycznie przez `FileResponse` gdy podamy `filename`.

### Auth dependency

Reuse istniejącego dependency z `users/api.py` lub `chat/api.py` (sprawdzić jak jest tam zaimplementowane `current_user`). Nazwy w specu (`get_current_user`) — zastąpić rzeczywistą.

### `ChatService.get_session_file`

```python
async def get_session_file(
    self,
    *,
    session_id: str,
    virtual_path: str,
    user: User,
) -> tuple[Path, str]:
    session = self.session_repository.get(session_id)
    if session is None:
        raise SessionNotFoundError(session_id)
    if session.user_id != user.id:
        raise SessionAccessDeniedError(session_id, user.id)

    fs_service = self._build_filesystem_service_for_session(session=session, user=user)
    return fs_service.download(virtual_path)
```

`SessionNotFoundError` i `SessionAccessDeniedError` to nowe wyjątki w `app/services/chat_service.py` (lub `app/domain/errors.py` jeśli tam żyją inne). Jeśli już istnieją z innych endpointów — reuse.

### `_build_filesystem_service_for_session`

Helper analogiczny do tego co `Runner` robi przed startem sesji. Buduje `AgentFilesystemService` z mountami:
- `agents/`, `shared/`, `skills/`, `workflows/` — read-only z `{user_workspace}/`
- `workspace/` mapowany na `{user_workspace}/workspaces/{date}/{session_id}/`

Wzorzec: skopiować logikę z `Runner._prepare_filesystem_service` (lub jak się tam nazywa) do `ChatService`. Lepiej **wyciągnąć ją wcześniej do helpera** w `WorkspaceLayoutService` lub osobnego `FilesystemFactory` żeby nie duplikować.

```python
class WorkspaceLayoutService:
    def build_filesystem_service_mounts(
        self,
        *,
        user: User,
        session: Session,
    ) -> list[FilesystemMount]:
        """Zwraca listę FilesystemMount-ów dla danej sesji.
        Reuse przez Runner i przez ChatService.get_session_file."""
        ...
```

Następnie obie strony (Runner i ChatService) wołają tę metodę i konstruują service z tymi mountami.

**Uwaga:** jeśli current `Runner` budzi service per-session w innym miejscu — sprawdzić tam i wykorzystać tę samą drogę. Cel: nie mieć dwóch ścieżek konstrukcji `AgentFilesystemService` z różnymi mountami.

---

## 3. Security

- Path traversal: `path_resolver.normalize_virtual_path` odrzuca `..`, leading `/`, absolute paths
- Mount enforcement: `path_resolver.resolve` rzuci jeśli ścieżka wybiega poza mount; `download` honoruje to
- Session ownership: `ChatService.get_session_file` sprawdza `session.user_id == user.id`
- File size: `MAX_FILE_SIZE` (już skonfigurowane dla read/write) cap'uje download
- Excluded patterns: `_is_excluded_path` blokuje `.git`, `__pycache__` itd. — bezpiecznie zwracamy 404 zamiast pliku
- Rate limiting: out-of-scope; użytkownik to single-user dev

Logowanie:
- ✅ Log path requested + session_id + user_id + status (success/denied/notfound)
- ❌ Nie logujemy zawartości pliku
- ❌ Nie logujemy media_type w plain text jeśli mógłby ujawnić sensitive info — w praktyce media_type nie jest sensitive

---

## 4. Pliki do stworzenia / zmiany

| Plik | Akcja |
|------|-------|
| `services/filesystem/base.py` | NOWY |
| `services/filesystem/local_service.py` | NOWY (z RENAME `service.py`) + dodanie `download()` |
| `services/filesystem/service.py` | USUNĄĆ |
| `services/filesystem/__init__.py` | Re-eksport |
| `services/filesystem/workspace_layout.py` | Dodać `build_filesystem_service_mounts` (jeśli celowo wyciągamy z Runner-a) |
| `runtime/runner.py` (lub miejsce konstrukcji service) | Użyć `build_filesystem_service_mounts` |
| `services/chat_service.py` | `get_session_file`, `_build_filesystem_service_for_session`, exceptions |
| `api/v1/chat/api.py` | Endpoint `download_session_file` |
| Wszystkie miejsca importujące `from app.services.filesystem.service` | Zmienić import na `from app.services.filesystem` (re-export) |

---

## 5. Kolejność implementacji

1. **`base.py`** — abstrakcyjna klasa
2. **Rename `service.py` → `local_service.py`** + dodanie `download()` + dziedziczenie z `AbstractFilesystemService`
3. **Aktualizacja importów** w całym repo (rg replace)
4. **`__init__.py`** — re-eksport
5. **Wyciągnięcie `build_filesystem_service_mounts`** (jeśli aktualnie zduplikowane lub inline w Runnerze)
6. **`ChatService.get_session_file`** + exceptions
7. **Endpoint** w `chat/api.py`
8. **Smoke test ręczny**: utworzyć sesję, agent zapisuje plik do `workspace/files/`, GET `/sessions/{id}/files/download?path=workspace/files/foo.txt` → bytes

Każdy krok można merge'ować osobno; krok 1–4 razem (jeden refaktor).

---

## Testy do dodania

- `tests/services/filesystem/test_local_service_download.py`
  - Plik istniejący w `workspace/` → zwraca `(abs_path, media_type)`
  - Plik nieistniejący → `FilesystemToolError`
  - Path traversal `../../../etc/passwd` → `FilesystemToolError`
  - Katalog zamiast pliku → `FilesystemToolError`
  - Plik > MAX_FILE_SIZE → `FilesystemToolError`
  - Plik w excluded path (`.git/HEAD`) → `FilesystemToolError`

- `tests/api/v1/chat/test_download.py`
  - Happy path: 200 z bajtami i Content-Disposition
  - 404: nieznana sesja
  - 403: sesja innego usera
  - 404: plik nie istnieje
  - Brak `path` param: 422
