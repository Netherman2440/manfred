# S02E04 — Mailbox (task `mailbox`)

Operacyjny spec dla rozwiązania zadania `mailbox` z lekcji AI devs S02E04. Obejmuje też trwałe ulepszenia w infrastrukturze agentów, które zostają z nami po lekcji.

## Cel zadania

Przeszukać skrzynkę mailową przez API zmail i wyciągnąć trzy wartości:
- `password` — hasło do systemu pracowniczego
- `date` (YYYY-MM-DD) — kiedy dział bezpieczeństwa planuje atak
- `confirmation_code` — kod ticketa (`SEC-` + 32 znaki)

Wynik POST do `hub.ag3nts.org/verify` z `task=mailbox`. Skrzynka aktywna — nowe maile mogą dochodzić w trakcie pracy.

## Zmiany

### 1. Nowy tool: `mail_api`

`src/app/tools/definitions/aidevs/mail_api.py`. POST do `<AI_DEVS_HUB_URL>/api/zmail`.

- Parametr `body` (object) — AI buduje pełny payload (`action`, `page`, `query`, `id`, …) na podstawie odpowiedzi `action: help`.
- Tool merguje `apikey` (z `AI_DEVS_API_KEY`) do body i wysyła. Klucz nigdy nie pojawia się w argumentach.
- Endpoint **fix** na `/api/zmail` — żaden parametr od AI. Zamknięta powierzchnia ataku.
- Zwraca `{status, body}` jak `submit_task`.

Rejestracja w `app/container.py` w `get_tools(...)` oraz reeksport w `app/tools/definitions/aidevs/__init__.py`.

### 2. Workflow per zadanie

Struktura: `.agent_data/default-user/workflows/aidevs/<task>.md` — jeden plik na każde zadanie kursu.

- **Generalne zasady** (one-knob, czytanie lekcji, post-mortem, format `results.md`, gdzie wstrzykiwany jest klucz API) → siedzą w **prompcie Azazela**. Bez tego startuje od zera w każdej sesji.
- **Per-task workflow** (`workflows/aidevs/<task>.md`) → strategia DLA TEGO ZADANIA: czy delegować do sub-agenta, jaki format `answer`, znane pułapki, post-mortem narastający.

Cel: między sesjami workflow konkretnego zadania **rośnie**. Następna sesja startuje z dorobku poprzedniej — wie, co zadziałało, co nie, jaką akcję API wykryto z `help`.

Dla S02E04 dodajemy: `workflows/aidevs/mailbox.md`.

### 3. Sub-agent `mailbox`

`.agent_data/default-user/agents/mailbox/mailbox.agent.md`. Tools: `mail_api`, `ask_user`, `submit_task`, `read_file`, `write_file`, `search_file`.

`ask_user` traktowany jest jako kanał „wiadomości do parent agenta" — pytanie bubble'uje się przez chain (Mailbox→Azazel→Manfred→operator). Nie dodajemy osobnego `message` toola w tej iteracji — alias `ask_user` z innym opisem to dług, a prawdziwa komunikacja parent-driven wymaga zmian w runnerze (parent jest WAITING, nie może przetwarzać tur). Do osobnego ticketa, jeśli kiedyś będziemy chcieli prawdziwą dwukierunkową komunikację bez angażowania operatora.

### 4. Azazel — odchudzenie + delegate

- Dodać `delegate` do `tools` w `azazel.agent.md`.
- Promptu: skrócić `<protocol>` — szczegóły idą do `workflows/aidevs/index.md`. Zostaje krótki bullet:
  - „Na początku zadania: `read_file(workflows/aidevs/index.md)`"
  - „Jeśli zadanie ma dedykowanego sub-agenta (np. `mailbox` dla S02E04) — `delegate`"
  - „Po zakończeniu (sukces lub porażka): zapisz rezultaty do `shared/aidevs/tasks/<task>/results.md` i zaktualizuj `workflows/aidevs/index.md` o nową wiedzę"

## Łańcuch delegacji

```
operator → Manfred (depth 0) → Azazel (1) → Mailbox (2)
```

`MAX_DELEGATION_DEPTH=8` — bez problemu.

## Pomijamy w tej iteracji

- **`message` tool między agentami** — wymagałoby zmian w `Runner._handle_agent_function_call` żeby parent mógł procesować turn podczas gdy child waiting. Na razie korzystamy z istniejącego chainu `ask_user` → propagacja do operatora.

## Weryfikacja

- `uv run pytest` — żadne istniejące testy nie powinny się wywalić
- Smoke: uruchomić server, sesja z Manfredem: „rozwiąż zadanie mailbox z S02E04"
- Oczekiwany finał: `{FLG:...}` od huba + zapis w `shared/aidevs/tasks/mailbox/results.md`
