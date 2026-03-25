# Plan implementacji historii sesji w backendzie

## Cel

Udostępnić historię sesji z backendu tak, aby frontend mógł:

- pobrać listę sesji użytkownika,
- wejść w szczegóły wybranej sesji,
- wyświetlić pełny przebieg sesji razem ze wszystkimi itemami i attachmentami,
- renderować historię bez opierania się o `localStorage`.

## Stan obecny

Backend zapisuje dane potrzebne do historii:

- `sessions`,
- `agents`,
- `items`,
- `attachments`.

Istnieją już fundamenty:

- `SessionRepository.list_by_user(...)`,
- `AgentRepository.list_by_session(...)`,
- `AttachmentRepository.list_by_item(...)`,
- trwałe `summary`, `created_at`, `updated_at` w modelu sesji.

Braki:

- brak endpointu `GET` do listy sesji,
- brak endpointu `GET` do szczegółu sesji,
- brak metody pobrania `items` dla całej sesji,
- brak agregacji danych do jednego stabilnego payloadu historii,
- `summary` istnieje w modelu, ale nie jest obecnie wyliczane.

## Decyzja projektowa

Rekomendowany wariant:

- backend zwraca szczegóły sesji już jako gotowe `entries[]` bliskie obecnemu modelowi feedu frontendu.

To ogranicza logikę po stronie UI i eliminuje heurystyki odtwarzania rozmowy z surowych `items`.

## Docelowe endpointy

### 1. Lista sesji

`GET /api/v1/chat/sessions`

Minimalna odpowiedź:

```json
{
  "sessions": [
    {
      "id": "sess_123",
      "rootAgentId": "agent_123",
      "status": "active",
      "summary": "Popraw parser PDF",
      "createdAt": "2026-03-24T08:00:00Z",
      "updatedAt": "2026-03-24T08:15:00Z"
    }
  ]
}
```

Opcjonalnie później:

- `lastMessagePreview`,
- `entryCount`,
- paginacja.

### 2. Szczegóły sesji

`GET /api/v1/chat/sessions/{session_id}`

Minimalna odpowiedź:

```json
{
  "sessionId": "sess_123",
  "rootAgentId": "agent_123",
  "status": "active",
  "summary": "Popraw parser PDF",
  "createdAt": "2026-03-24T08:00:00Z",
  "updatedAt": "2026-03-24T08:15:00Z",
  "entries": []
}
```

Rekomendacja:

- `entries[]` powinno być kompatybilne z obecnym feedem frontendu:
  - `message` dla wpisu usera,
  - `agent_response` dla odpowiedzi agenta,
  - attachmenty przypięte do odpowiednich wpisów,
  - `createdAt` na każdym wpisie.

## Etapy implementacji

### Etap 1. Rozszerzyć warstwę repozytoriów

Do dodania:

- `ItemRepository.list_by_session(session_id)`
- `AttachmentRepository.list_by_session(session_id)` lub alternatywnie mechanizm pobrania attachmentów dla wszystkich `item_id` z sesji

Wymagania:

- kolejność `items` po `sequence` lub po `created_at`, zależnie od docelowego modelu,
- kolejność `attachments` po `created_at`.

### Etap 2. Zdefiniować modele domenowe historii

Dodać modele transportowe lub domenowe dla:

- `SessionListItem`,
- `SessionListResponse`,
- `SessionDetailResponse`,
- `SessionHistoryEntry`,
- `SessionHistoryMessageEntry`,
- `SessionHistoryAgentResponseEntry`.

Cel:

- oddzielić model historii od aktualnego `ChatResponse`,
- uniknąć mieszania payloadu jednej tury z payloadem pełnej sesji.

### Etap 3. Zbudować serwis historii sesji

Nowy serwis, np. `SessionHistoryService`, powinien obsłużyć:

- `list_sessions(user_id)`
- `get_session_detail(user_id, session_id)`

Zakres odpowiedzialności:

- pobrać sesję,
- pobrać wszystkich agentów sesji,
- pobrać wszystkie itemy sesji,
- pobrać attachmenty sesji,
- złożyć gotowe `entries[]`.

### Etap 4. Ustalić sposób składania `entries[]`

Najważniejszy punkt implementacyjny.

Minimalny wariant bez migracji schematu:

- traktować wiadomość usera root agenta jako początek tury,
- kolejne itemy root agenta przypisać do odpowiedzi tej tury,
- dla odpowiedzi agenta zachować obecny model `agents[]`, jeśli da się go odtworzyć z istniejących danych,
- attachmenty przypinać po `item_id`.

Ryzyko:

- bez jawnego `turn_id` składanie tur będzie heurystyczne.

Lepszy wariant docelowy:

- dodać jawne `turn_id` do nowych `items`,
- z czasem oprzeć historię o ten identyfikator.

Rekomendacja:

- etap 1 wdrożyć heurystykę,
- etap 2 zaplanować dodanie `turn_id`, jeśli historia stanie się krytyczną funkcją.

### Etap 5. Obsłużyć `summary`

Na start:

- jeśli `session.summary` jest puste, generować fallback z pierwszej wiadomości usera,
- przyciąć preview do ustalonej długości.

Później można dodać:

- aktualizację `summary` po każdej turze,
- osobny job do generacji lepszego podsumowania.

### Etap 6. Wystawić endpointy i schematy API

Dodać:

- schematy Pydantic do listy sesji,
- schematy Pydantic do szczegółu sesji,
- handlery w `app/api/v1/chat/api.py`.

Scenariusze błędów:

- `404` dla nieistniejącej sesji,
- `404` lub `403` dla sesji nienależącej do użytkownika, jeśli dojdzie prawdziwy auth.

### Etap 7. Testy

Testy repozytoriów i serwisu:

- pobieranie sesji usera,
- poprawna kolejność elementów historii,
- poprawne przypięcie attachmentów,
- fallback dla pustego `summary`.

Testy API:

- `GET /api/v1/chat/sessions` zwraca listę,
- `GET /api/v1/chat/sessions/{id}` zwraca szczegóły,
- `404` dla błędnego `session_id`.

## Proponowana kolejność prac

1. Dodać brakujące metody repozytoriów.
2. Dodać `SessionHistoryService`.
3. Dodać payload listy sesji.
4. Dodać payload szczegółu sesji.
5. Wystawić endpointy `GET`.
6. Uzupełnić testy.
7. Na końcu dopracować `summary` i ewentualnie paginację.

## Ryzyka

- brak `turn_id` może utrudnić jednoznaczne składanie starych sesji,
- jeśli frontend będzie potrzebował dokładnie obecnego modelu `AgentResponse`, backend musi odtworzyć strukturę agentów z historii, a nie tylko zwrócić płaskie `items`,
- `summary` bez osobnej strategii będzie tylko prostym preview.

## Rekomendacja końcowa

Nie wystawiać szczegółu sesji jako surowego dumpa `items[]`.

Lepiej zwrócić gotowe `entries[]`, bo:

- frontend ma już renderer feedu,
- łatwiej zachować zgodność z obecnym UI,
- mniej logiki mapującej po stronie klienta,
- prostsze testy end-to-end.
