# Plan MVP: Sessions API dla frontendu

## Cel

Przygotować minimalny backendowy zakres prac potrzebny do uruchomienia frontendu przeciwko prawdziwemu API Manfreda w scenariuszu:

- frontend ładuje sesje `default-user`,
- frontend otwiera historię wybranej sesji,
- frontend wysyła pierwszą wiadomość bez `session_id`,
- backend tworzy sesję i zwraca `session_id`,
- frontend po refreshu widzi nową sesję i jej transcript.

Ten dokument opisuje tylko backendowy zakres MVP. Szerszy kontrakt cross-repo jest opisany w:
- `/home/netherman/code/manfred/docs/frontend-backend-api-contract-mapping.md`

## Zakres MVP

Backend musi dostarczyć:
- `GET /users/{user_id}/sessions`
- `GET /users/{user_id}/sessions/{session_id}`
- istniejący `POST /chat/completions` bez zmian łamiących kompatybilność

Backend nie musi w tym etapie dostarczać:
- `POST /users/{user_id}/sessions`
- zmian w `deliver`
- nowych eventów runtime
- zmian w streamingu
- auth i current-user endpointu

## Kontrakt produktu dla tego repo

### `GET /users/{user_id}/sessions`

Endpoint zwraca listę sesji użytkownika posortowaną malejąco po `updated_at`.

Minimalny response:

```json
{
  "data": [
    {
      "id": "session-id",
      "user_id": "default-user",
      "title": null,
      "status": "active",
      "root_agent_id": "agent-id",
      "root_agent_name": "Manfred",
      "root_agent_status": "completed",
      "waiting_for_count": 0,
      "last_message_preview": "Ostatnia wiadomość lub odpowiedź",
      "created_at": "2026-04-17T10:00:00Z",
      "updated_at": "2026-04-17T10:01:00Z"
    }
  ]
}
```

Zasady:
- jeśli użytkownik nie ma sesji, zwracamy `200` z pustą listą,
- nie tworzymy żadnych nowych rekordów podczas odczytu,
- `last_message_preview` jest opcjonalne, ale rekomendowane,
- `root_agent_status` i `waiting_for_count` mają zasilać lewą kolumnę frontendu.

### `GET /users/{user_id}/sessions/{session_id}`

Endpoint zwraca pełny read-model sesji.

Minimalny response:

```json
{
  "data": {
    "session": {
      "id": "session-id",
      "user_id": "default-user",
      "title": null,
      "status": "active",
      "created_at": "2026-04-17T10:00:00Z",
      "updated_at": "2026-04-17T10:01:00Z"
    },
    "root_agent": {
      "id": "agent-id",
      "name": "Manfred",
      "status": "completed",
      "model": "openrouter:model",
      "waiting_for": []
    },
    "items": []
  }
}
```

Zasady:
- jeśli sesja nie istnieje albo nie należy do `user_id`, zwracamy `404`,
- `items` są sortowane rosnąco po `sequence`,
- endpoint ma zwracać co najmniej itemy:
  - `message`
  - `function_call`
  - `function_call_output`
- jeśli w bazie istnieje `reasoning`, backend nie może się wywrócić na serializacji; może je zwrócić technicznie, nawet jeśli frontend jeszcze ich nie pokazuje.

### `POST /chat/completions`

W ramach tego etapu nie zmieniamy semantyki endpointu.

Warunki, które muszą pozostać prawdziwe:
- brak `session_id` tworzy nową sesję,
- response zawiera `session_id`,
- response zawiera `agent_id`,
- istniejąca sesja nadal działa przez `session_id`,
- endpoint pozostaje kompatybilny z obecnym requestem i responsem.

## Model danych do wystawienia

### Lista sesji

Backendowy read-model listy powinien korzystać z:
- `SessionRepository.list_by_user(...)`
- `AgentRepository.get(session.root_agent_id)`
- ostatniego sensownego itemu sesji dla preview

Minimalne pola do wyliczenia:
- `root_agent_name`
- `root_agent_status`
- `waiting_for_count`
- `last_message_preview`

### Detail sesji

Backendowy read-model detalu powinien korzystać z:
- `SessionRepository.get(...)`
- `AgentRepository.get(session.root_agent_id)`
- `ItemRepository.list_by_session(...)`

Mapowanie itemów:
- `message`:
  - `role`
  - `content`
- `function_call`:
  - `call_id`
  - `name`
  - `arguments` po deserializacji `arguments_json`
- `function_call_output`:
  - `call_id`
  - `name`
  - `tool_result` po deserializacji `output`
  - `is_error`

## Zakres zmian w kodzie

### Nowe pliki

- `src/app/api/v1/users/api.py`
- `src/app/api/v1/users/schema.py`
- `src/app/services/session_query_service.py`

### Zmiany w istniejących plikach

- `src/app/api/v1/api.py`
  - podpięcie routera `users`
- `src/app/container.py`
  - rejestracja `SessionQueryService`
- `src/app/main.py`
  - opcjonalnie CORS, jeśli frontend będzie odpalany jako Flutter Web

### Testy

- `src/tests/`
  - test listy sesji dla użytkownika
  - test pustej listy sesji
  - test detalu sesji
  - test `404` dla sesji innego użytkownika lub nieistniejącej
  - test serializacji `function_call`
  - test serializacji `function_call_output`

## Decyzje implementacyjne

### Osobny query service

Read API dla sesji nie powinno rozrastać `ChatService`.

Rekomendacja:
- dodać osobny `SessionQueryService`,
- trzymać w nim wyłącznie logikę read-modelu,
- zostawić `ChatService` jako write-path i execution-path.

### Brak mutacji przy odczycie

Endpointy `GET /users/...` nie mogą:
- tworzyć użytkownika,
- tworzyć sesji,
- naprawiać danych „po cichu”.

Jeżeli danych brakuje lub są niespójne, endpoint ma zwracać kontrolowany błąd zamiast robić ukryte side effecty.

### CORS

Jeśli frontend będzie uruchamiany jako Flutter Web, backend potrzebuje CORS.

Minimalna rekomendacja:
- dodać konfigurację originów do `config.py`,
- podpiąć `CORSMiddleware` w `main.py`,
- odzwierciedlić zmianę w `.env.EXAMPLE`.

Jeśli etap implementacji będzie dotyczył tylko aplikacji natywnej, CORS można odłożyć, ale dokument powinien jawnie to zaznaczać.

## Acceptance Criteria

- backend wystawia `GET /users/{user_id}/sessions`,
- backend wystawia `GET /users/{user_id}/sessions/{session_id}`,
- `POST /chat/completions` pozostaje kompatybilne,
- read-model sesji zwraca `message`, `function_call` i `function_call_output`,
- frontend może na `default-user` odczytać listę sesji i transcript wybranej sesji,
- wysłanie pierwszej wiadomości bez `session_id` tworzy sesję widoczną później w `GET /users/{user_id}/sessions`.

## Test Plan

- test integracyjny listy sesji zwracającej rekordy w kolejności `updated_at desc`,
- test integracyjny pustej listy dla `default-user`,
- test integracyjny detalu sesji z transcriptowym `items`,
- test jednostkowy deserializacji `arguments_json`,
- test jednostkowy deserializacji `output` do `tool_result`,
- test integracyjny flow:
  - `POST /chat/completions` bez `session_id`
  - `GET /users/default-user/sessions`
  - `GET /users/default-user/sessions/{new_session_id}`

## Handoff: backend

Done:
- Zawężono backendowy zakres do read API i kompatybilności z istniejącym `chat/completions`.

Contract:
- Read API dla sesji jest osobnym query-path i nie mutuje stanu.
- `chat/completions` pozostaje jedynym mechanizmem tworzenia nowej sesji w MVP.

Next role:
- `integrator`

Risks:
- Brak CORS zablokuje Flutter Web mimo poprawnego kontraktu HTTP.
- Jeśli `last_message_preview` będzie liczone niekonsekwentnie, lewa kolumna i detal mogą wyglądać niespójnie.
