# Auth: Bearer Token, Login, Refresh

## Cel

Wprowadzić warstwę autentykacji JWT bearer token do całego API backendu, żeby aplikacja mogła być bezpiecznie hostowana na VPSie. Każdy endpoint poza `/auth/*` i `/health` wymaga ważnego access tokenu. Userzy tworzeni przez CLI; brak publicznej rejestracji.

Specyfikacja jest self-contained dla backendu i opisuje pełny kontrakt API z klientem.

## Kontekst lokalny

Stan obecny backendu:
- `UserModel` w [user.py](../../src/app/db/models/user.py) ma kolumny `id`, `name`, `api_key_hash` (nieużywane), `created_at`.
- `SessionModel` w [session.py](../../src/app/db/models/session.py) ma już `user_id: FK -> users.id` z indeksem.
- Wszystkie ścieżki HTTP są niechronione; serwer zakłada jednego "default" usera tworzonego z [config.py](../../src/app/config.py) (`DEFAULT_USER_ID`, `DEFAULT_USER_NAME`) i wstrzykiwanego w [container.py](../../src/app/container.py).
- `ChatService` w [chat_service.py](../../src/app/services/chat_service.py) ma już `_ensure_default_user()` i kontrole `PermissionError` przy odwołaniu do sesji innego usera. Cała logika multi-user jest gotowa, brakuje tylko źródła `current_user`.
- `GET /users/me` w [users/api.py](../../src/app/api/v1/users/api.py) zwraca hardcoded `DEFAULT_USER_ID`. `GET /users/{user_id}/sessions` i `GET /users/{user_id}/sessions/{session_id}` biorą `user_id` z path bez walidacji - po wprowadzeniu auth byłby to IDOR.
- Endpointy chat w [chat/api.py](../../src/app/api/v1/chat/api.py) obejmują: `POST /chat/completions` (JSON lub multipart, opcjonalny SSE), `PATCH /chat/sessions/{id}/items/{id}` (edit, opcjonalny SSE), `POST /chat/sessions/{id}/queue`, `POST /chat/agents/{id}/deliver`, `POST /chat/sessions/{id}/cancel`.
- Inne routery: [agents/api.py](../../src/app/api/v1/agents/api.py), [tools/api.py](../../src/app/api/v1/tools/api.py), [models/api.py](../../src/app/api/v1/models/api.py) - wszystkie obecnie bez auth.
- Filesystem ma per-user workspaces w `.agent_data/<user-key>/` (`workspace_layout.py`).

Powód zmiany teraz: deploy na VPS bez auth = otwarty proxy do OpenRouter API key oraz pełen dostęp do plików userów w `.agent_data/`.

## Scope

In-scope:
- Refactor `users` table: drop `name`, drop `api_key_hash`, add `username` (UNIQUE NOT NULL) i `password_hash` (NOT NULL).
- Hash haseł algorytmem **argon2** (lib `argon2-cffi`).
- Endpointy auth: `POST /auth/login`, `POST /auth/refresh`. Brak logout endpointu (stateless).
- JWT access + refresh, oba podpisywane HS256 sekretem z env (`JWT_SECRET`). Stateless, brak tabeli refresh tokens, brak listy revoke.
- `get_current_user` jako FastAPI dependency wpięte na poziomie routerów `chat`, `users`, `agents`, `tools`, `models`. Zwalnia tylko `/auth/*` i `/health`.
- Zmiana path: wszystkie endpointy `/users/{user_id}/...` przechodzą na `/users/me/...` (literał `me` mapowany na `current_user.id` w handlerze). Stary kształt path zostaje usunięty.
- CLI: `uv run python -m app.cli create-user --username X` (interaktywny prompt na hasło, dwukrotne potwierdzenie). Plus subcommand `reset-password --username X`.
- Wywalenie `DEFAULT_USER_ID`, `DEFAULT_USER_NAME`, `Container.user_id_default`, `Container.user_name_default`, `_ensure_default_user()`. Każde miejsce, które dziś bierze defaultowego usera z configu, musi brać go z `get_current_user`.
- Migracja Alembic: drop wszystkich wierszy z `users`, `sessions`, `items`, `agents`, `queued_inputs`, `item_attachments`, potem zmiana schematu users. Clean slate.
- Skasowanie folderu `.agent_data/default-user/` (poza migracją DB; udokumentowane w README sekcji deploy).
- Settings dodaje: `JWT_SECRET` (required, brak default), `JWT_ACCESS_EXPIRES_MIN=15`, `JWT_REFRESH_EXPIRES_DAYS=30`. `.env.EXAMPLE` aktualizowane.
- Testy jednostkowe (hash/verify, JWT encode/decode, dependency happy/sad path) i integracyjne (login → access endpoint → 401 bez tokenu, refresh flow).

Out-of-scope:
- Rate limiting na `/auth/login` i `/auth/refresh` (świadomie odpuszczone, do dorobienia później).
- Mechanizm odwołania (revoke) tokenów: brak `token_version`, brak tabeli refresh tokens, brak `last_login_at`. Wyciek refresh tokenu pozostaje ważny do końca jego expiry. Brutalny revoke = bump `JWT_SECRET` w env + restart serwera (kasuje wszystkie sesje wszystkich userów).
- Endpoint do zmiany hasła z UI (`/auth/change-password`). Reset hasła wyłącznie przez CLI.
- Walidacja siły hasła (minimum długość/znaki) - akceptujemy dowolne niepuste.
- Endpoint rejestracji (`/auth/register`).
- Multi-factor auth, OAuth, SSO.
- Audit log prób logowania (nie zapisujemy failed attempts ani last_login_at).

## Kontrakt z klientem

### Format JWT

Oba tokeny podpisane HS256 sekretem `JWT_SECRET`. Claimy:
- `sub` - user id (string).
- `type` - `"access"` albo `"refresh"`.
- `iat` - issued at (unix seconds).
- `exp` - expiry (unix seconds).

Bez kustomowych claimów (`token_version`, scope, role - poza zakresem).

### POST /auth/login

Request (JSON):
```json
{ "username": "string", "password": "string" }
```

Response 200:
```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "token_type": "bearer",
  "access_expires_in": 900,
  "refresh_expires_in": 2592000
}
```

Response 401: `{ "detail": "Invalid credentials" }` - jednakowy komunikat dla braku usera oraz złego hasła (nie ujawniamy istnienia username).

Response 400 dla pustego/za krótkiego body.

### POST /auth/refresh

Request (JSON):
```json
{ "refresh_token": "<jwt>" }
```

Response 200:
```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "token_type": "bearer",
  "access_expires_in": 900,
  "refresh_expires_in": 2592000
}
```

Wydaje nowy access **i** nowy refresh (rotacja - klient zawsze nadpisuje oba). Stary refresh nie jest odwoływany (stateless) - to świadoma uproszczona semantyka.

Response 401:
- Token wygasł
- Podpis nie matchuje (zły secret)
- `type != "refresh"`
- User wskazany w `sub` nie istnieje w DB

### Autoryzacja zwykłych endpointów

Header: `Authorization: Bearer <access_token>`

Response 401 (`{ "detail": "..." }`):
- Brak headera
- Format inny niż `Bearer <token>`
- Token wygasł
- Podpis nie matchuje
- `type != "access"`
- User wskazany w `sub` nie istnieje

Wszystkie 401 zwracają `WWW-Authenticate: Bearer` zgodnie ze standardem.

### Endpointy zwolnione z auth

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/health`

Wszystkie pozostałe wymagają ważnego access tokenu.

### Zmiana shape /users

Stare (do usunięcia):
- `GET /api/v1/users/me` - zostaje, ale zwraca dane z `current_user`
- `GET /api/v1/users/{user_id}/sessions` - **usuwane**
- `GET /api/v1/users/{user_id}/sessions/{session_id}` - **usuwane**

Nowe:
- `GET /api/v1/users/me` - bez zmian semantyki dla klienta (struktura odpowiedzi taka sama):
  ```json
  { "id": "string", "name": "string" }
  ```
  Pole `name` w response = `username` z DB (alias na warstwie schemy, żeby nie psuć frontu).
- `GET /api/v1/users/me/sessions` - lista sesji bieżącego usera (semantyka identyczna jak stara `/users/{user_id}/sessions`).
- `GET /api/v1/users/me/sessions/{session_id}` - szczegóły sesji bieżącego usera.

Wewnętrznie: handler bierze `user_id` z `current_user.id`, nie z path. Path `me` nie wchodzi do żadnego zapytania DB.

### Sesje i autoryzacja zasobów

`current_user.id` w handlerze automatycznie staje się ownerem nowych sesji (`SessionModel.user_id`). Próba dostępu do cudzej sesji (np. `chat/sessions/{id}/queue` gdzie session.user_id != current_user.id) zwraca **403 Forbidden** - już dziś jest tam `PermissionError` w `chat_service.py`, handler ma go mapować na 403 (już istnieje w [chat/api.py](../../src/app/api/v1/chat/api.py)).

## Plan zmian

### Schemat i migracja
- [db/models/user.py](../../src/app/db/models/user.py): drop `name`, drop `api_key_hash`, add `username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)`, add `password_hash: Mapped[str] = mapped_column(String(255), nullable=False)`.
- Domena [domain/user.py](../../src/app/domain/user.py): `User` zyskuje `username`, `password_hash`, traci `name`, `api_key_hash`.
- Repo [domain/repositories/user_repository.py](../../src/app/domain/repositories/user_repository.py): metoda `get_by_username(username) -> User | None`.
- Alembic revision: upgrade =
  1. `DELETE FROM item_attachments; DELETE FROM items; DELETE FROM queued_inputs; DELETE FROM agents; DELETE FROM sessions; DELETE FROM users;`
  2. `ALTER TABLE users DROP COLUMN api_key_hash; DROP COLUMN name; ADD COLUMN username VARCHAR(255) NOT NULL UNIQUE; ADD COLUMN password_hash VARCHAR(255) NOT NULL;`
  3. Downgrade odwrotny (rekonstrukcja kolumn jako nullable, bez przywracania danych).

### Hash haseł
- Nowy moduł `app/security/passwords.py`: `hash_password(plain) -> str`, `verify_password(plain, hashed) -> bool`. Korzysta z `argon2.PasswordHasher` z domyślnymi parametrami.
- Dodać `argon2-cffi` do `pyproject.toml`.

### JWT
- Nowy moduł `app/security/tokens.py`:
  - `create_access_token(user_id) -> str`
  - `create_refresh_token(user_id) -> str`
  - `decode_token(token, expected_type) -> TokenPayload` - rzuca `InvalidTokenError` przy expiry/signature/type mismatch.
- Czyta `JWT_SECRET`, `JWT_ACCESS_EXPIRES_MIN`, `JWT_REFRESH_EXPIRES_DAYS` z settings.
- Lib: `pyjwt`.

### Dependency
- Nowy moduł `app/api/v1/auth/dependencies.py`: `get_current_user(authorization: str = Header(...), db_session, user_repository) -> User`. Parsuje `Bearer <token>`, dekoduje, ładuje usera z DB, rzuca `HTTPException(401)` z `WWW-Authenticate: Bearer` przy każdym błędzie.

### Endpointy auth
- Nowy plik `app/api/v1/auth/api.py`:
  - `POST /auth/login` - waliduje body (`username` + `password` niepuste), pobiera usera przez `get_by_username`, weryfikuje hasło, wystawia oba tokeny.
  - `POST /auth/refresh` - dekoduje refresh token, ładuje usera, wystawia nową parę.
- Nowy `app/api/v1/auth/schema.py`: pydantic models dla request/response.
- `app/api/v1/api.py`: dodaje `auth_router` przed innymi routerami, `prefix="/auth"`, **bez** `Depends(get_current_user)` na nim. Pozostałe routery: dodaje `dependencies=[Depends(get_current_user)]` na `include_router(...)` (FastAPI propaguje na wszystkie endpointy w danym routerze).

### Zmiana shape /users i propagacja current_user
- [users/api.py](../../src/app/api/v1/users/api.py):
  - `GET /users/me`: zamiast czytać `DEFAULT_USER_ID`, używa `current_user: User = Depends(get_current_user)`. Usuwa cały blok auto-tworzenia default-usera, zachowuje `workspace_layout_service.ensure_user_workspace(user)`. Response: `{id, name: username}`.
  - `GET /users/{user_id}/sessions` → `GET /users/me/sessions` (handler bierze `current_user`, ignoruje fragment path `me`).
  - `GET /users/{user_id}/sessions/{session_id}` → `GET /users/me/sessions/{session_id}` analogicznie.
- [services/chat_service.py](../../src/app/services/chat_service.py): wywalić `_ensure_default_user()`. Wszystkie metody publiczne, które do tej pory wołały tę funkcję, dostają teraz `user: User` jawnym parametrem (lub przez konstruktor) - wybór: jawny parametr w sygnaturach metod, bo `ChatService` jest tworzony per-request przez DI i może dostać `current_user` z `Depends`. Wpiąć w routery chat.
- [container.py](../../src/app/container.py): wywalić `user_id_default`, `user_name_default`, ich providery. `Container.chat_service` zostaje, ale fabryka serwisu nie odwołuje się już do tych ustawień.

### CLI
- Nowy plik `app/cli.py` używający `typer`:
  - `create-user --username <str>` - `getpass()` dwa razy, weryfikuje równość, zapisuje usera z hashem.
  - `reset-password --username <str>` - znajduje usera, `getpass()`, nadpisuje `password_hash`.
- Entry point: `uv run python -m app.cli <command>`. Dodać `typer` do `pyproject.toml` (jeśli nie ma).

### Config
- [config.py](../../src/app/config.py): drop `DEFAULT_USER_ID`, `DEFAULT_USER_NAME`. Add `JWT_SECRET: str` (bez default - Pydantic poleci błąd przy starcie jeśli brak). Add `JWT_ACCESS_EXPIRES_MIN: int = 15`, `JWT_REFRESH_EXPIRES_DAYS: int = 30`.
- [.env.EXAMPLE](../../src/.env.EXAMPLE): wywalić `DEFAULT_USER_*`, dodać `JWT_SECRET=` (z komentarzem "generate with: openssl rand -hex 32"), `JWT_ACCESS_EXPIRES_MIN=15`, `JWT_REFRESH_EXPIRES_DAYS=30`.

### Deploy hygiene
- Sekcja w README backendu: po zaaplikowaniu migracji wykonać:
  ```
  rm -rf .agent_data/default-user
  uv run python -m app.cli create-user --username <twoj-login>
  ```

## Ryzyka

- **Wyciek refresh tokenu** = pełny dostęp do końca expiry (30 dni). Brak revoke. Mitigacja awaryjna: bump `JWT_SECRET` + restart serwera (kasuje wszystkich userów).
- **Brak rate limitu** na `/auth/login` umożliwia brute force online. Argon2 spowalnia atakującego, ale obciąża też serwer. Świadomy trade-off; do dorobienia.
- **Migracja kasuje dane**. Akceptowalne dla dev/single-user środowiska; udokumentowane w upgrade docs.
- **Endpointy `/users/{user_id}/...` znikają**: klient na starym shape API dostanie 404 (nie 401). Akceptowalne, bo zmiana idzie razem z aktualizacją frontu.
- **Argon2 hash time**: ~50-100ms na request login. Akceptowalne dla pojedynczego usera.
- **Stream SSE i expiry**: token sprawdzany tylko przy nawiązaniu połączenia. Długi stream przeżyje wygaśnięcie access tokenu - akceptowalne, nie zmieniamy tego.
- **Token w logach**: nie loguj headera `Authorization` w access logach (sprawdzić middleware Loguru/Uvicorn).

## Acceptance Criteria

- `POST /auth/login` z poprawnym username + hasłem zwraca dwa JWT, oba dekodowalne tym samym `JWT_SECRET`.
- `POST /auth/login` ze złym hasłem zwraca 401 z `{"detail": "Invalid credentials"}` w czasie podobnym do poprawnego hasła (argon2 verify zawsze działa).
- `POST /auth/refresh` z ważnym refresh tokenem zwraca nową parę. Z access tokenem zwraca 401 (`type != refresh`).
- Każdy endpoint z poza `/auth/*` i `/health` bez headera Authorization zwraca 401 z `WWW-Authenticate: Bearer`.
- `GET /users/me` zwraca `{id, name}` gdzie `name == username` zalogowanego usera.
- `GET /users/me/sessions` zwraca tylko sesje bieżącego usera.
- Próba dostępu do sesji innego usera (po manualnym podstawieniu cudzego session_id) zwraca 403.
- CLI: `uv run python -m app.cli create-user --username foo` tworzy usera, hasło można potem użyć w `/auth/login`.
- CLI: `reset-password --username foo` nadpisuje hash, stare hasło przestaje działać, nowe działa.
- Stary endpoint `/users/{user_id}/sessions` zwraca 404.
- Brak `JWT_SECRET` w env = serwer nie startuje (Pydantic validation error).

## Test Plan

Testy jednostkowe (pytest):
- `security/passwords.py` - hash + verify, verify niepoprawne hasło, hash dwóch identycznych haseł daje różne wyniki (salt).
- `security/tokens.py` - encode + decode round-trip, decode wygasłego tokenu, decode z zepsutym podpisem, decode access tokenu z `expected_type=refresh`.
- `get_current_user` dependency - brak headera, zły format, expired token, nieistniejący user, happy path.

Testy integracyjne (FastAPI TestClient, in-memory SQLite):
- Login happy path → access + refresh w response.
- Login wrong password → 401.
- Endpoint chroniony bez tokenu → 401.
- Endpoint chroniony z ważnym tokenem → 200.
- Endpoint chroniony z expired tokenem → 401.
- Refresh happy path → nowa para tokenów.
- `/users/me` zwraca dane zalogowanego usera.
- `/users/me/sessions` zwraca tylko sesje bieżącego usera (z setupem dwóch userów i krzyżową sesją).
- Dostęp do sesji innego usera przez `chat/sessions/{id}/queue` → 403.

Test manualny:
- CLI: stworzyć usera, zalogować się przez curl, użyć tokenu w request do `/users/me`.

## Rollout / Backward Compatibility

- Brak BC: po deployu klient bez tokenu (i klient na starym `/users/{id}/...` path) nie działa wcale.
- Migracja Alembic kasuje wszystkie dane DB. Po `alembic upgrade head` wykonać manualnie:
  ```
  rm -rf .agent_data/default-user
  uv run python -m app.cli create-user --username <login>
  ```
- Frontend musi być deployowany jednocześnie (lub po) z nową wersją backendu.
