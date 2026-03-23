# Plan aktualizacji API chat/completions pod załączniki i voice

## Cel

Zaktualizować komunikację między `manfred` i `manfred_frontend` tak, aby:

- UI mogło wysyłać zwykłe pliki i obrazy,
- UI mogło nagrywać wiadomości głosowe,
- wszystkie pliki trafiały od razu do `workspace/input/...`,
- do kontekstu pojedynczej tury trafiała także tekstowa referencja `attachments: [...]`,
- transkrypcja audio odbywała się po stronie backendu,
- kontrakt API był zgodny z podejściem z S01/S02:
  - osobny etap ingestu plików,
  - session-scoped workspace,
  - jawne, proste dane wejściowe dla LLM,
  - referencje do plików zamiast polegania wyłącznie na binarnych uploadach.

## Stan obecny

- `POST /api/v1/chat/completions` przyjmuje tylko `message` i opcjonalne `sessionId`.
- Backend ma już `WORKSPACE_ROOT`, narzędzia plikowe, image tools oraz audio service z transkrypcją plików zapisanych w workspace.
- Frontend nadal jest oparty o legacy kontrakt `/api/v1/chat` + `thread_id`, więc już teraz nie jest w pełni zgodny z aktualnym backendem.
- Brakuje warstwy uploadu plików, metadanych załączników i powiązania ich z sesją/chat turnem.

## Założenia projektowe wynikające z S01/S02

1. Pliki nie powinny żyć wyłącznie w payloadzie requestu do modelu. Powinny mieć trwałą referencję w przestrzeni roboczej.
2. LLM musi dostać prostą, tekstową informację o dostępnych załącznikach, żeby mógł odwoływać się do nich w narzędziach.
3. Workspace powinien być organizowany per sesja, nawet jeśli utrzymujemy główny prefiks `workspace/input`.
4. Audio powinno być traktowane jak zwykły załącznik, ale z dodatkowym krokiem backendowej transkrypcji.

## Rekomendowany docelowy kontrakt

### 1. `POST /api/v1/chat/attachments`

Nowy endpoint do ingestu plików z UI.

`Content-Type: multipart/form-data`

Pola requestu:

- `sessionId` opcjonalne
- `files[]` wymagane
- `source` opcjonalne: `file_picker | voice_recording | paste | drag_drop`

Zachowanie:

- jeśli `sessionId` nie istnieje albo nie zostało przesłane, backend tworzy nową sesję i zwraca jej ID,
- każdy plik zapisuje do `workspace/input/<sessionId>/...`,
- backend rozpoznaje typ załącznika: `image | document | audio | other`,
- dla `audio/*` backend wykonuje transkrypcję od razu po zapisie pliku,
- backend zapisuje metadane załącznika w bazie,
- endpoint zwraca gotowe referencje do użycia przez `chat/completions`.

Rekomendowana odpowiedź:

```json
{
  "sessionId": "sess_123",
  "attachments": [
    {
      "id": "att_123",
      "kind": "audio",
      "mimeType": "audio/webm",
      "originalFilename": "voice-message.webm",
      "workspacePath": "input/sess_123/20260323_101530_voice-message.webm",
      "sizeBytes": 182340,
      "transcription": {
        "status": "completed",
        "text": "Przygotuj podsumowanie tego nagrania."
      }
    }
  ]
}
```

Uwagi:

- Ścieżka nadal spełnia wymóg `workspace/input`, ale dzięki podkatalogowi sesji nie mieszamy plików między rozmowami.
- W kolejnych iteracjach można dodać datę przed `sessionId`, np. `input/2026-03-23/<sessionId>/...`, ale nie jest to wymagane na start.

### 2. `POST /api/v1/chat/completions`

Endpoint pozostaje głównym punktem uruchomienia tury rozmowy, ale przechodzi na wejście bardziej zgodne z agentowym workflow.

`Content-Type: application/json`

Rekomendowany request:

```json
{
  "sessionId": "sess_123",
  "message": "Przeanalizuj załączniki i opisz najważniejsze wnioski.",
  "attachmentIds": ["att_123", "att_456"]
}
```

Walidacja:

- `message` może być puste tylko wtedy, gdy istnieje co najmniej jeden załącznik,
- `attachmentIds` muszą należeć do tej samej sesji,
- jeśli załącznik audio nie ma gotowej transkrypcji, backend powinien wykonać ją przed zbudowaniem wejścia do LLM.

### 3. Budowanie wejścia do LLM

Backend nie powinien przekazywać do modelu jedynie samego `message`. Powinien złożyć finalny input z:

- tekstu użytkownika,
- dopisku `attachments: [...]` z referencjami do `workspacePath`,
- opcjonalnych metadanych załączników,
- opcjonalnych transkrypcji audio.

Rekomendowany format pierwszej wersji:

```text
<message od użytkownika>

attachments:
- input/sess_123/photo.png
- input/sess_123/brief.pdf
- input/sess_123/voice-message.webm

audio_transcriptions:
- input/sess_123/voice-message.webm => "Przygotuj plan wdrożenia..."
```

To jest dokładnie wzorzec z S01E04: plik istnieje fizycznie w workspace, a agent dostaje też jego tekstową referencję do dalszej pracy z narzędziami.

### 4. Opcjonalne rozszerzenie multimodalne

Pierwsza wersja powinna opierać się na referencjach tekstowych i narzędziach. Dopiero w drugim kroku warto dodać:

- natywne image blocks dla `image/*` przy modelach vision,
- przekazywanie binarnych obrazów obok tekstowej referencji.

Tekstowa referencja do `workspacePath` powinna pozostać kanoniczna, bo jest potrzebna narzędziom i współdzieleniu kontekstu.

## Zmiany domenowe i infrastrukturalne

### Nowe modele i persistence

Dodać tabelę `attachments` oraz repozytorium, przykładowe pola:

- `id`
- `session_id`
- `agent_id` nullable
- `item_id` nullable
- `kind`
- `mime_type`
- `original_filename`
- `stored_filename`
- `workspace_path`
- `size_bytes`
- `source`
- `transcription_status`
- `transcription_text`
- `created_at`

Relacje:

- załącznik należy do sesji,
- po wysłaniu wiadomości załączniki są przypisywane do user item albo do chat turnu.

### Nowe serwisy

1. `AttachmentStorageService`
   - zapis plików do `workspace/input/<sessionId>/...`
   - sanitizacja nazw
   - walidacja MIME, rozszerzeń i limitów rozmiaru

2. `AttachmentService`
   - tworzenie metadanych
   - klasyfikacja typu załącznika
   - pobieranie attachmentów po ID
   - weryfikacja przynależności do sesji

3. `ChatInputBuilder`
   - składanie finalnej wiadomości użytkownika do itemu i provider payloadu
   - dokładanie `attachments: [...]`
   - dokładanie `audio_transcriptions: [...]`

4. `AudioIngestionService` albo rozszerzenie `AttachmentService`
   - wywołanie istniejącego `AudioService.transcribe_audio(...)`
   - zapis wyniku transkrypcji do bazy

### Zmiany w `ChatService`

- `ChatRequest` musi obsłużyć `attachmentIds`,
- `prepare_chat_turn()` powinno ładować attachmenty i przekazywać je do buildera wejścia,
- tworzony `user_item.content` nie powinien być już równy surowemu `message`,
- observability powinna logować także listę attachmentów,
- odpowiedź API powinna zawierać attachmenty przypisane do user turnu i ewentualne statusy transkrypcji.

## Zmiany w promptach i zachowaniu agenta

System prompt powinien dostać krótki dopisek:

- pliki użytkownika są dostępne w `workspace/input/...`,
- jeśli w wiadomości pojawia się sekcja `attachments`, agent ma odwoływać się do tych ścieżek przy narzędziach,
- jeśli istnieje sekcja `audio_transcriptions`, traktuje ją jako pomocniczy opis audio, ale źródłowy plik nadal istnieje w workspace.

To nie powinno być rozbudowane. Zgodnie z S02 wystarczy generalna informacja o roli workspace i referencji do plików.

## Migracja endpointów

### Faza 1

- dodać `POST /api/v1/chat/attachments`,
- rozszerzyć `POST /api/v1/chat/completions`,
- utrzymać dotychczasowe `message + sessionId` jako kompatybilny wariant bez attachmentów.

### Faza 2

- usunąć frontendowe zależności od legacy `/api/v1/chat`,
- opcjonalnie dodać tymczasowy compatibility field `message` w odpowiedzi, jeśli potrzebny do rolloutu.

### Faza 3

- jeśli frontend będzie już czytał `output[]`, można zrezygnować z aliasów zgodności.

## Testy

### Backend unit/integration

- upload pojedynczego pliku tekstowego zapisuje plik do `workspace/input/<sessionId>/...`
- upload obrazu zwraca `kind=image`
- upload audio zapisuje plik i generuje transkrypcję
- `chat/completions` z `attachmentIds` buduje poprawny content user itemu
- załącznik z obcej sesji jest odrzucany
- pusta wiadomość bez attachmentów daje `422`
- wiadomość z samym audio attachmentem działa poprawnie

### Ryzyka do kontrolowania

- frontend nie może generować własnego `thread_id` i traktować go jak prawdziwego `sessionId`,
- transkrypcja nie może uruchamiać się wielokrotnie dla tego samego audio,
- ścieżki muszą być bezwzględnie ograniczone do workspace,
- trzeba rozstrzygnąć limity rozmiaru plików i akceptowane MIME.

## Kolejność implementacji

1. Dodać persistence dla attachmentów.
2. Dodać storage service i endpoint uploadu.
3. Zintegrować upload audio z transkrypcją.
4. Rozszerzyć `ChatRequest`, `ChatService` i budowanie user inputu.
5. Dodać response payload z attachment metadata.
6. Zaktualizować prompt systemowy.
7. Dodać testy integracyjne.

## Definition of Done

- UI może wysłać plik lub nagranie bez bezpośredniego wpychania binariów do `chat/completions`,
- każdy załącznik trafia do `workspace/input/<sessionId>/...`,
- `chat/completions` dostaje referencje `attachments: [...]`,
- audio jest transkrybowane na backendzie i wynik trafia do kontekstu,
- frontend korzysta z jednego, spójnego kontraktu opartego o `sessionId`, nie `thread_id`.
