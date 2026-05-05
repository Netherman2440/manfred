# Basic chat improvements

## Cel

Repo-local celem backendu jest dostarczenie spójnego kontraktu persistence, workspace i runtime dla trzech funkcji:
- attachments powiązanych z wiadomością usera,
- edycji wcześniejszego user itemu z rewindem historii,
- kolejkowania nowej wiadomości podczas aktywnego runu.

Ta specyfikacja jest self-contained i opisuje backendowy zakres bez potrzeby czytania frontendu.

## Kontekst lokalny

Stan obecny backendu:
- `POST /api/v1/chat/completions` przyjmuje JSON i zapisuje tylko gołe `message` itemy w [chat_service.py](../../src/app/services/chat_service.py),
- `WorkspaceLayoutService` umie zapewnić katalog `input` per sesja w [workspace_layout.py](../../src/app/services/filesystem/workspace_layout.py),
- `ItemModel` i domenowy `Item` nie mają miejsca na attachment metadata ani pola edycji,
- `SessionQueryService` serializuje transcript sesji bez attachmentów i bez semantyki rewindu,
- `Runner` ma już cancellation-aware flow i SSE checkpointy, ale nie ma mailboxa nowych wiadomości.

Powód tej zmiany teraz:
- wcześniejszy task streaming/cancel odblokował aktywny run jako produktowy flow,
- filesystem/workspace daje miejsce na fizyczne pliki wejściowe,
- teraz trzeba domknąć podstawowe interakcje użytkownika zamiast utrzymywać chat jako sam tekst bez rewindu i bez kolejki.

## Scope

In-scope:
- multipart-capable send/edit/queue endpoints w API chat,
- persistence attachmentów i attachment storage service pod session workspace `input`,
- transcript session details rozszerzony o attachment metadata i pola `is_edited` / `edited_at`,
- rewind historii od wskazanego user itemu,
- cleanup zależnych itemów, waiting state i child agentów po rewindzie,
- session-scoped queue mailbox dla nowych wiadomości podczas aktywnego runu,
- runtime checkpointy konsumujące queue,
- manifest attachmentów przekazywany do modelu jako dodatkowy kontekst.

Out-of-scope:
- provider-native file uploads, vision lub multimodal parts w requestach do OpenRouter,
- edycja assistant/tool items,
- branchowanie historii i przechowywanie wielu wersji transcriptu,
- queue dla `deliver_result(...)`,
- pełna fizyczna kasacja osieroconych plików jako warunek v1.

## Kontrakt wejściowy i wyjściowy

### API z frontendem

`POST /api/v1/chat/completions`
- wspiera:
  - legacy JSON dla wiadomości bez attachmentów,
  - `multipart/form-data` dla wiadomości z plikami,
- fields dla multipart:
  - `message: str`
  - `session_id?: str`
  - `stream?: bool`
  - `include_tool_result?: bool`
  - `attachments[]: UploadFile`
- zachowanie:
  - jeśli brak aktywnego runu dla wskazanej sesji, endpoint zachowuje się jak dziś i uruchamia run,
  - jeśli request jest JSON-only i bez attachmentów, zachowanie ma pozostać kompatybilne wstecz.

`PATCH /api/v1/chat/sessions/{session_id}/items/{item_id}`
- używany tylko dla `message` itemu z `role=user`,
- akceptuje multipart:
  - `message: str`
  - `stream?: bool`
  - `retain_attachment_ids[]?: str`
  - `attachments[]?: UploadFile`
- zachowanie:
  - walidacja ownershipu sesji i edytowalności itemu,
  - aktualizacja tekstu i attachment setu wskazanego itemu,
  - rewind historii po `item_id`,
  - restart root runu od tego punktu,
  - `stream=true` zwraca SSE analogiczne do `/chat/completions`.

`POST /api/v1/chat/sessions/{session_id}/queue`
- używany dla sesji, której root agent jest aktualnie w `running` albo `waiting`,
- akceptuje multipart:
  - `message: str`
  - `attachments[]?: UploadFile`
- response:
  - `session_id`
  - `queued_input_id`
  - `accepted_at`
  - `queue_position`
- jeśli root agent jest w `waiting`, queued input zostaje zapisany, ale nie jest konsumowany, dopóki agent nie wyjdzie z `waiting`.

Transcript session details:
- `message` item zyskuje:
  - `attachments: list[AttachmentSchema]`
  - `is_edited: bool`
  - `edited_at: datetime | null`
- `AttachmentSchema` minimum:
  - `id`
  - `file_name`
  - `media_type`
  - `size_bytes`
  - `path`

### API layer <-> runtime

`ChatService` ma nowe odpowiedzialności:
- zamienić request HTTP na:
  - canonical user item,
  - zapisane attachmenty,
  - opcjonalny queued envelope,
- przy edit wykonać rewind przed odpaleniem `Runner`,
- przy queue nie odpalać drugiego runu, tylko zapisać input do mailboxa powiązanego z sesją/root agentem,
- utrzymać spójność DB i filesystemu przy błędach.

`Runner` ma:
- dostać dostęp do mailboxa queued inputów,
- sprawdzać queue na checkpointach:
  - przed buildem requestu do providera,
  - po tool execution,
  - po child agent return,
  - przed terminalnym `completed`,
- materializować queued input do zwykłych `Item`s przed następną turą,
- przy mapowaniu items do provider input dodawać attachment-aware inputy związane z daną user wiadomością.

### Runtime <-> providers/tools/MCP

W v1 provider nadal otrzymuje tekstowy input:
- attachmenty są przekładane na providerowe inputy powiązane z daną user wiadomością,
- path musi być zgodny z filesystem toolami, nie absolutny host path,
- implementacja ma dwa poziomy:
  - docelowo: rozszerzyć provider abstraction tak, aby pojedynczy user item mógł mieć `attachments`,
  - fallback v1: dla jednego domenowego user itemu wygenerować sekwencję provider inputów:
    - pierwszy `ProviderMessageInputItem` z tekstem wiadomości,
    - następnie po jednym synthetic `ProviderMessageInputItem` per attachment z informacją:
      - `Attached file: <file_name>`
      - `media_type: ...`
      - `size_bytes: ...`
      - `path: input/<resolved_name>`

Narzucona semantyka:
- attachment info ma dotyczyć konkretnej wiadomości, nie całej sesji globalnie,
- kolejność w provider input ma być deterministyczna,
- queued wiadomości po materializacji trafiają do historii dokładnie jak zwykłe user itemy.

## Moduły do zmiany

API i schemy:
- `src/app/api/v1/chat/api.py`
- `src/app/api/v1/chat/schema.py`

Service:
- `src/app/services/chat_service.py`
- nowy attachment storage service, np. `src/app/services/chat_attachments.py`

Runtime:
- `src/app/runtime/runner.py`
- nowy mailbox/signal module, np. `src/app/runtime/message_queue.py`

Persistence:
- `src/app/db/models/item.py`
- nowe modele, np.:
  - `src/app/db/models/item_attachment.py`
  - `src/app/db/models/queued_input.py`
- domena:
  - `src/app/domain/item.py`
  - nowe domenowe typy attachment/queued input
- repozytoria:
  - `src/app/domain/repositories/item_repository.py`
  - nowe repo attachmentów i queue
- migracje Alembic

Session transcript:
- `src/app/services/session_query_service.py`
- `src/app/api/v1/users/schema.py`

Filesystem / DI:
- `src/app/services/filesystem/workspace_layout.py`
- `src/app/container.py`

Testy:
- `src/tests/test_chat_service.py`
- `src/tests/test_chat_stream_api.py`
- `src/tests/test_sessions_api.py`
- nowe testy rewind/attachments/queue

## Oczekiwane zachowanie

### Attachments

1. Request z attachmentami trafia do backendu jako multipart.
2. Backend zapewnia session workspace i zapisuje pliki pod:
   - `.../<session_id>/input/<file_name>`
   - przy kolizji nazwy używany jest suffix w stylu `<file_name>(1)`.
3. Tworzony jest canonical user `Item`.
4. Dla itemu zapisywane są attachment rekordy z metadata i tool-visible path.
5. Przy budowie provider input runner dodaje attachment-aware inputy dla tej wiadomości.

### Edit / rewind

1. Frontend wskazuje `session_id` i `item_id` wcześniejszej wiadomości usera.
2. Backend odrzuca request, jeśli:
   - item nie należy do user message,
   - sesja należy do innego usera,
   - item należy do sub-wątku albo do agenta innego niż root transcript sesji.
3. Backend aktualizuje wybrany item i jego attachment set.
4. Backend usuwa z kanonicznej historii wszystkie nowsze itemy sesji.
5. Backend resetuje root agenta i zależnych child agentów do stanu zgodnego z historią do tego miejsca.
6. Backend uruchamia run od zedytowanej wiadomości i zwraca standardowy response/stream.

### Queue

1. Podczas aktywnego root runu przychodzi nowa wiadomość na `/queue`.
2. Backend zapisuje queued input i ewentualne attachmenty w session workspace.
3. Endpoint zwraca acknowledgement bez otwierania nowego streamu.
4. Runner przy najbliższym checkpointcie:
   - pobiera queued inputy FIFO,
   - materializuje je do zwykłych user itemów,
   - kontynuuje następną turę z rozszerzoną historią.
5. Jeśli agent jest w `waiting`, krok 4 nie zachodzi, dopóki stan `waiting` nie zostanie rozwiązany.

## Decyzje architektoniczne

- Attachment persistence ma być osobna od `items.output/arguments_json`; nie upychamy attachment metadata jako luźnego JSON-a w istniejących polach.
- Queue ma być osobnym mailboxem/persistence, a nie "ukrytym itemem" już obecnym w transcriptcie.
- Rewind jest liniowy i destrukcyjny dla nowszej historii kanonicznej.
- Path dla modelu ma być generowany przez backendowy resolver kompatybilny z filesystem mountami.
- Filesystem write powinien mieć staging/finalize semantics albo wyraźną strategię cleanupu po rollbacku.
- Edit jest dozwolony także w stanie `waiting`, ale tylko dla root transcriptu; nie wspieramy edycji wiadomości w sub-wątkach.

## Edge cases

- edit wiadomości w sesji `waiting`:
  - jest dozwolony dla wiadomości w root transcriptcie,
  - rewind musi wyczyścić bieżący waiting state i nowszą historię tak, aby nowy run startował z czystego punktu,
  - edycja wiadomości w sub-wątkach pozostaje zabroniona,
- queue request przychodzi, ale run dochodzi do `waiting` zanim queue zostanie skonsumowana:
  - queued input nie może zostać samowolnie potraktowany jako `deliver`,
  - powinien zostać w mailboxie jako pending aż do wyjścia agenta ze stanu `waiting`,
- attachment upload kończy się sukcesem na dysku, ale DB transakcja pada:
  - backend musi mieć cleanup strategy,
- dwa identyczne filename w jednej wiadomości:
  - storage ma je rozróżnić bez utraty oryginalnej nazwy użytkowej,
- rewind przez punkt sprzed delegacji:
  - child agenty i ich itemy nie mogą pozostać aktywne ani widoczne w transcriptcie.

## Acceptance Criteria

- backend zapisuje attachmenty w `session/input` i zwraca ich metadata w session details,
- nazewnictwo plików w `session/input` jest płaskie i kolizyjnie bezpieczne (`file.ext`, `file(1).ext`, ...),
- provider input zawiera attachment-aware inputy powiązane z właściwą wiadomością usera,
- istnieje endpoint edycji user itemu z rewindem historii,
- po edit nowsze itemy znikają z kanonicznej historii i root run startuje od nowa,
- istnieje queue endpoint przyjmujący nową wiadomość podczas aktywnego runu,
- runner konsumuje queue bez uruchamiania drugiego równoległego runu dla tej samej sesji, a jeśli sesja jest w `waiting`, queue pozostaje pending,
- `cancel`, `deliver` i dotychczasowy send bez attachmentów pozostają kompatybilne.

## Test plan

- testy jednostkowe:
  - attachment storage service,
  - serializacja transcriptu z attachment metadata,
  - rewind repository/service flow,
  - message queue mailbox FIFO i checkpoint semantics.
- testy integracyjne:
  - multipart send z attachmentami i finalnym transcript itemem,
  - edit starego user message z wycięciem nowszych itemów,
  - queue nowej wiadomości podczas aktywnego streamu i jej późniejsza materializacja,
  - session details zwraca `attachments`, `is_edited`, `edited_at`.
- test manualny:
  - wysłać plik tekstowy i sprawdzić jego obecność na dysku oraz w transcriptcie,
  - zedytować pierwszą wiadomość po delegacji i sprawdzić cleanup child agentów,
  - podczas długiego tool calla zakolejkować kolejną wiadomość i sprawdzić jej obsługę po checkpointcie.

## Handoff: planner

Done:
- Zdefiniowano backendowy kontrakt dla attachment uploadu, rewindu i queue mailboxa.
- Wskazano główne moduły: chat API/service, persistence, session query, runtime mailbox.

Contract:
- Attachmenty są first-class metadata powiązaną z user itemem i plikiem w `session/input`.
- Queue nie tworzy drugiego runu; runner konsumuje ją na checkpointach.

Next role:
- `manfred_backend`

Risks:
- Spójność DB + filesystem.
- Cleanup rewindu przez granice child agentów.
- Semantyka queue wobec `waiting`.
