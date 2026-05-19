# Observational Memory

## Cel

Repo-local celem backendu jest dostarczenie pelnego asynchronicznego pipeline'u obserwacji i refleksji dla agentow Manfreda:
- subscribery `Observer` i `Reflector` reagujace na eventy z `EventBus`,
- prompt injection memory.md + `current-task` + `suggested-response` w `Runner._build_provider_request`,
- endpoint `POST /api/v1/chat/sessions/{session_id}/summarize` do recznego wyzwalania,
- nowy typ Item `OBSERVATION` z polem `state` do prezentacji w UI,
- feature flag `OBSERVATIONAL_MEMORY_ENABLED` jako kill-switch.

Ta specyfikacja jest self-contained i opisuje backendowy zakres bez potrzeby czytania frontendu.

## Kontekst lokalny

Stan obecny backendu:
- `EventBus` jest synchroniczny ([event_bus.py](../../src/app/events/event_bus.py)) z 13 typami eventow,
- najblizszy odpowiednik `graph.completed` z heyfibo to `TurnCompletedEvent` ([runner.py](../../src/app/runtime/runner.py) linia 193, 398) emitowany po kazdym turnie agenta,
- `Runner._build_provider_request(...)` ([runner.py](../../src/app/runtime/runner.py) linia 1572) komponuje system prompt z `loaded_agent.system_prompt`,
- `WorkspaceLayoutService` ([workspace_layout.py](../../src/app/services/filesystem/workspace_layout.py)) scopuje filesystem per `<user_key>/<mount>`,
- `FilesystemService` ma mount `agents/` w FS_ROOTS - czyli `.agent_data/<user>/agents/<name>/` jest writable przez `write_file` tool,
- `ItemRepository` ([db/](../../src/app/db/)) trzyma items per AgentRun (kolumna `agent_id`),
- domena `Session` ([domain/session.py](../../src/app/domain/session.py)) ma `id`, `user_id`, `root_agent_id`, `status`, `created_at`, `updated_at`,
- domena `Agent` (AgentRun) ma `parent_id`, `root_agent_id`, `depth` ([runner.py](../../src/app/runtime/runner.py) linia 1348-1353).

Powod tej zmiany teraz:
- agenci nie maja zadnej pamieci miedzy turnami poza biezacym kontekstem providera,
- przy dlugich sesjach kontekst providera jest sztucznie wypelniony historia, co zwieksza koszty i powoduje hallucynacje,
- frontend potrzebuje endpointu do recznego summarize'a (slash command + idle timer).

## Scope

In-scope:
- migracja Alembic (kolumny Session + enum value Item),
- pakiet `app/services/memory/` (token counter, message formatter, memory service, observe use case, prompts),
- nowe definicje eventow `observation.*` i `reflection.*`,
- subscribery `ObserverSubscriber`, `ReflectorSubscriber`,
- modyfikacja `Runner._build_provider_request` o injection memory + continuation,
- endpoint `POST /chat/sessions/{session_id}/summarize`,
- emit eventow `observation.*` przez SSE pipeline,
- wiring w `container.py` z feature flag,
- testy jednostkowe i integracyjne.

Out-of-scope:
- vector store / embeddings dla obserwacji,
- summary dla subagentow recznie (observer auto-odpalany dla subagentow przez TurnCompleted),
- inne slash-komendy niz `/summarize`,
- backend-driven idle scheduler (cron / background) - idle to FE-only,
- distributed lock (redis / file-lock) dla wielo-procesowych deployments,
- migracja istniejacych sesji do nowych kolumn (kolumny nullable),
- `MAX_OBSERVATION_DEPTH` dla rekurencyjnych subagentow.

## Kontrakt wejsciowy i wyjsciowy

### API z frontendem

`POST /api/v1/chat/sessions/{session_id}/summarize`
- request body: puste (`{}` akceptowane),
- response:
  - `202 Accepted` z payload `{"status": "started" | "locked", "observation_item_id": "<uuid>"}` - obserwacja zostala uruchomiona lub jest juz w toku (drugie wywolanie idempotentne),
  - `204 No Content` - 0 nieobserwowanych itemow dla root_agenta sesji, no-op,
  - `404 Not Found` - sesja nie istnieje lub nie nalezy do biezacego usera,
  - `503 Service Unavailable` - `OBSERVATIONAL_MEMORY_ENABLED=false`.

Eventy SSE dodane do pipeline `chat_service.py` (rozszerzenie istniejacych SSE streamow oraz nowa subskrypcja dla `/chat/sessions/{id}/stream`-podobnego kanalu na potrzeby observacji odpalanej recznie):
- `observation.started` payload: `{session_id, agent_name, item_id, message_count, token_count}`,
- `observation.success` payload: `{session_id, agent_name, item_id, new_observations_preview, token_count}` (preview = pierwsze 200 znakow),
- `observation.failure` payload: `{session_id, agent_name, item_id, reason}` (reason: `locked` / `error`),
- `reflection.started`, `reflection.success` (opcjonalne, frontend moze ignorowac).

`Item` rozszerzony:
- `ItemType.OBSERVATION` (nowa wartosc enum),
- pole `state` na `Item` (nullable string, dotyczy tylko OBSERVATION na razie): `in_progress` | `done`,
- `content` zawiera preview obserwacji (skrocone), `output` zawiera pelny tekst nowych obserwacji.

### API layer <-> runtime

`ChatService.summarize_session(session_id, user_id) -> SummarizeResponse`:
- pobiera Session, weryfikuje `Session.user_id == user_id`,
- liczy `unobserved_items = ItemRepository.get_items_for_agent(session.root_agent_id, after_item_id=session.last_observed_item_id)`,
- jesli `len(unobserved_items) == 0` -> zwraca 204,
- jesli lock `(user_id, root_agent.name)` zajety -> tworzy Item OBSERVATION w state `done` z output `"Juz trwa podsumowanie"`, emit `observation.failure(locked)`, zwraca 202,
- inaczej:
  - tworzy Item OBSERVATION state `in_progress`,
  - `asyncio.create_task(ObserveUseCase.execute(...))` (fire-and-forget),
  - zwraca 202 z item_id.

`ObserveUseCase.execute(*, session_id, agent_run_id, agent_name, user_id, item_id, force=False)`:
- acquiruje lock `(user_id, agent_name)` (jesli `force=True` - waitable; inaczej non-blocking i emit failure(locked)),
- ladowanie istniejacego memory.md przez `FilesystemService.read_file(".agent_data/<user>/agents/<name>/memory.md")` - None gdy brak,
- liczy `unobserved_items` z `ItemRepository`,
- jesli `not force and token_count < TOKENS_TO_OBSERVE` -> emit nothing, update item do `done` z output `"Below threshold"` (albo skip itemu calkiem - decyzja w implementacji),
- emit `ObservationStartedEvent`,
- wola `MemoryService.observe(existing, unobserved_items)` -> `ObservationResult(observations, current_task, suggested_response)`,
- zapisuje:
  - append do `memory.md` (z separatorem `\n\n`),
  - update `Session.last_observed_item_id`, `Session.current_task`, `Session.suggested_response` (tylko gdy `agent_run_id == session.root_agent_id`),
  - update Item OBSERVATION do `state=done`, `output=result.observations`, `content=preview`,
- emit `ObservationSuccessEvent`,
- release lock.

### Runtime <-> Providers / Tools / MCP

`Runner._build_provider_request(...)` (runner.py:1572) - rozszerzenie:
- jesli `OBSERVATIONAL_MEMORY_ENABLED=False` -> bez zmian,
- inaczej, dla biezacego AgentRuna:
  - resolve sciezka memory.md przez `WorkspaceLayoutService.resolve_user_workspace(user_id).root / "agents" / agent_name / "memory.md"`,
  - jesli plik istnieje:
    - czytaj zawartosc,
    - skomponuj `system_message_with_memory = system_prompt + "\n\n" + memory_log_prompt(observations=content)`,
    - jesli AgentRun jest root_agentem sesji i `Session.current_task` lub `Session.suggested_response` niepuste:
      - append `<current-task>...</current-task>\n<suggested-response>...</suggested-response>` do system_message,
    - dodaj `memory_log_continuation()` jako user-role message z `<system-reminder>` PRZED ostatnia user message,
  - jesli plik nie istnieje - bez zmian.

`MemoryService.observe(existing, items) -> ObservationResult`:
- formatuje `items` przez `MessageFormatter.format(items)`,
- buduje human content:
  - z `existing`: `<existing-observations>\n{existing}\n</existing-observations>\n\n<new-messages>\n{formatted}\n</new-messages>`,
  - bez `existing`: `{formatted}`,
- wola providera (osobny client z `OBSERVER_LLM_MODEL`) z system message `observe_prompt()`,
- parsuje response: tagi `<observations>`, `<current-task>`, `<suggested-response>` regex,
- zwraca `ObservationResult(observations, current_task, suggested_response)`.

`MemoryService.reflect(observations) -> str`:
- wola providera z system message `reflect_prompt()` i human message `observations`,
- zwraca pelny content (oczekiwany jest blok `<observations>...</observations>` plus opcjonalnie `<current-task>` i `<suggested-response>` - reflector moze tez aktualizowac te pola, decyzja: TYLKO observations sa zapisywane do memory.md, current_task/suggested_response z reflectora sa zapisywane do Session jesli sa).

Filesystem + lock:
- `dict[tuple[str, str], asyncio.Lock]` w `MemoryLockRegistry` (nowa klasa, singleton w containerze) - klucz `(user_id, agent_name)`,
- pisanie do memory.md w trakcie obserwacji jest chronione tym lockiem; observer akwiruje lock przed czytaniem, zwalnia po zapisie,
- reflector korzysta z tego samego locka (refleksja nie moze isc rownolegle z obserwacja tego samego agenta).

### Persistence

Migracja Alembic `XXXX_observational_memory.py`:
- `op.add_column("sessions", sa.Column("last_observed_item_id", sa.String(length=64), nullable=True))` (FK opcjonalny - dla SQLite uproszczone),
- `op.add_column("sessions", sa.Column("current_task", sa.Text, nullable=True))`,
- `op.add_column("sessions", sa.Column("suggested_response", sa.Text, nullable=True))`,
- `op.add_column("items", sa.Column("state", sa.String(length=32), nullable=True))`,
- enum `ItemType` w SQLite to VARCHAR z check constraint - migracja musi:
  - dropnac stary check constraint,
  - dodac nowy z `OBSERVATION` jako dozwolona wartoscia,
  - lub uzyc batch_alter_table dla SQLite.

Brak migracji danych - wszystkie nowe kolumny nullable.

### Events

Nowe pliki w `app/events/definitions/`:
- `observation_started.py`:
  ```python
  @dataclass
  class ObservationStartedEvent(BaseEvent):
      type: Literal["observation.started"] = "observation.started"
      session_id: str = ""
      agent_name: str = ""
      item_id: str = ""
      message_count: int = 0
      token_count: int = 0
  ```
- `observation_success.py` (analogicznie + `new_observations: str`, `token_count: int`),
- `observation_failure.py` (analogicznie + `reason: Literal["locked", "error"]`),
- `reflection_started.py`, `reflection_success.py`.

Eksport w `app/events/definitions/__init__.py` i `app/events/__init__.py`.

### Subscribers

`app/events/subscribers/observer.py`:
```python
class ObserverSubscriber:
    def __init__(self, event_bus, observe_use_case, token_counter, item_repository, session_repository, agent_repository, memory_lock_registry, settings):
        ...

    async def handle(self, event: TurnCompletedEvent) -> None:
        if not self._settings.OBSERVATIONAL_MEMORY_ENABLED:
            return
        # resolve agent_name, user_id z event.ctx
        # check lock per-(user_id, agent_name)
        # jesli lock zajety -> emit ObservationFailureEvent(reason="locked"), return
        # count unobserved tokens
        # jesli < TOKENS_TO_OBSERVE -> return (cichy no-op)
        # inaczej -> spawn asyncio.create_task(ObserveUseCase.execute(...))
```

`app/events/subscribers/reflector.py`:
```python
class ReflectorSubscriber:
    async def handle(self, event: ObservationSuccessEvent) -> None:
        if not self._settings.OBSERVATIONAL_MEMORY_ENABLED:
            return
        memory_path = workspace_layout.resolve_user_workspace(...) / "agents" / agent_name / "memory.md"
        content = filesystem_service.read_file(memory_path)
        tokens = token_counter.count_tokens_str(content)
        if tokens < TOKENS_TO_REFLECT:
            return
        # acquire same lock
        emit ReflectionStartedEvent
        reflected = await memory_service.reflect(content)
        filesystem_service.write_file(memory_path, reflected)
        emit ReflectionSuccessEvent
```

EventBus jest synchroniczny - `handle` jest async, wiec `handler` w EventBus musi byc wrapowany w `asyncio.create_task`. Sprawdzic obecny pattern `EventBus.emit` i ewentualnie dodac scheduling do executor poola (jak `langfuse_subscriber` to robi - patrz `app/observability/langfuse_subscriber.py`).

### Container wiring

`app/container.py` (warunkowy fragment):
```python
if settings.OBSERVATIONAL_MEMORY_ENABLED:
    memory_lock_registry = MemoryLockRegistry()
    observer_provider = providers.Singleton(create_observer_provider(settings))
    memory_service = MemoryService(provider=observer_provider, ...)
    observe_use_case = ObserveUseCase(memory_service, filesystem_service, item_repository, session_repository, agent_repository, event_bus, settings, memory_lock_registry)
    observer_subscriber = ObserverSubscriber(event_bus, observe_use_case, token_counter, ..., memory_lock_registry, settings)
    reflector_subscriber = ReflectorSubscriber(event_bus, memory_service, filesystem_service, token_counter, memory_lock_registry, settings)
    observer_subscriber.subscribe(event_bus)
    reflector_subscriber.subscribe(event_bus)
```

Container ma dostac:
- `MemoryLockRegistry` jako singleton,
- `MemoryService` jako singleton (provider observera, prompty),
- `ObserveUseCase` jako singleton (orchestration),
- subscribery jako singletony zarejestrowane w event_bus.

### Config

`app/config.py` rozszerzenie `Settings`:
```python
OBSERVATIONAL_MEMORY_ENABLED: bool = False
TOKENS_TO_OBSERVE: int = 30_000
TOKENS_TO_REFLECT: int = 40_000
OBSERVER_LLM_MODEL: str = "openai/gpt-4o-mini"
```

`.env.EXAMPLE`:
```
# Observational memory
OBSERVATIONAL_MEMORY_ENABLED=false
TOKENS_TO_OBSERVE=30000
TOKENS_TO_REFLECT=40000
OBSERVER_LLM_MODEL=openai/gpt-4o-mini
```

### Filesystem policy (memory.md i agent tools)

`memory.md` jest w mount `agents/` ktory jest widoczny dla narzedzi `read_file` / `write_file` / `manage_file`:
- agent ma **pelny read + write** do swojego `memory.md` (path w jego folderze `agents/<name>/memory.md`),
- nie blokujemy w policy - to swiadoma decyzja, agent moze sam wzbogacac pamiec,
- reflector tez pisze przez `FilesystemService.write_file` - wspolny lock zapobiega kolizji.

## Plan

PR1 (single backend PR):
1. Migracja Alembic.
2. Config + `.env.EXAMPLE`.
3. Pakiet `app/services/memory/` (token_counter, message_formatter, memory_service, observe_use_case, prompts).
4. Eventy `observation.*` i `reflection.*`.
5. Subscribery + `MemoryLockRegistry`.
6. Modyfikacja `Runner._build_provider_request` o injection (pod feature flag).
7. Endpoint `POST /chat/sessions/{id}/summarize` + SSE emit.
8. Wiring w `container.py`.
9. Testy jednostkowe.
10. Testy integracyjne dla pipeline'u.

## Ryzyka

- emit observation/reflection events synchronicznie przez EventBus blokowalby request - wszystkie handlery musza schedulowac do background tasks (jak `langfuse_subscriber.py`); zweryfikowac obecny pattern,
- LangFuse trace span dla observera musi byc rozdzielny od trace'a agenta - inaczej wszystko sklei sie w jeden context,
- migracja SQLite enum (`ItemType`) - jesli istnieje check constraint, batch_alter_table jest wymagany; sprawdzic czy ItemType jest enum DB czy String z aplikacyjnym constraint,
- rownolegle requesty `/summarize` na ta sama sesja - drugi musi byc no-op (lock + idempotency),
- agent piszacy do `memory.md` przez `write_file` poza lockiem - to jest swiadome, ale w polowie observera moglby nadpisac plik; akceptowalne ryzyko na MVP, monitorowac.

## Acceptance Criteria

- po `TurnCompletedEvent` w sesji z unobserved > 30k tokenow plik `<user>/agents/<root_agent>/memory.md` zyskuje nowy blok,
- `Session.last_observed_item_id` = ostatni Item ID z observacji,
- `Session.current_task` i `Session.suggested_response` sa wypelnione gdy observer je wyextrahowal,
- `Item(type=OBSERVATION, state=done)` istnieje w bazie z output pelnych obserwacji,
- przy nastepnym wywolaniu providera w tej sesji system prompt zawiera memory_log + current_task + suggested_response + continuation,
- endpoint `POST /chat/sessions/{id}/summarize`:
  - na sesji bez unobserved zwraca 204,
  - na sesji z unobserved zwraca 202 i obserwacja sie odpala asynchronicznie,
  - przy zajetym locku zwraca 202 z `status=locked` i Item w `done` ze stosownym output,
  - przy `OBSERVATIONAL_MEMORY_ENABLED=false` zwraca 503,
- przy `OBSERVATIONAL_MEMORY_ENABLED=false`:
  - subscribery nie sa zarejestrowane w EventBus,
  - `Runner._build_provider_request` nie czyta memory.md i nie injektuje continuation,
- testy przechodza na `uv run pytest`.

## Test Plan

- testy jednostkowe (`tests/services/memory/`):
  - `test_token_counter.py` - rozne typy `Item` (MESSAGE z content str, FUNCTION_CALL z arguments_json, FUNCTION_CALL_OUTPUT z output, REASONING),
  - `test_message_formatter.py` - format z timestampem i bez, role mapping, JSON args dla tool calls,
  - `test_memory_service.py` - mock providera, parsing tagow `<observations>`, `<current-task>`, `<suggested-response>`,
  - `test_observe_use_case.py` - 0 unobserved (no-op), below threshold non-force, force=True na 0 unobserved, lock zajety, normalny happy path,
  - `test_observer_subscriber.py` - feature flag off, lock zajety -> emit failure, lock wolny -> schedule task,
  - `test_reflector_subscriber.py` - below/above TOKENS_TO_REFLECT.
- testy integracyjne (`tests/integration/`):
  - `test_observational_memory_e2e.py` - sesja -> turn -> TurnCompletedEvent -> observer -> memory.md istnieje -> Session.last_observed_item_id ustawione -> kolejny turn ma memory w system message,
  - `test_summarize_endpoint.py` - 204 / 202 / 503 / 404 cases,
  - `test_feature_flag_off.py` - subscribery nie zarejestrowane, endpoint 503.
- test manualny:
  - `uv run python -m app.main` z `OBSERVATIONAL_MEMORY_ENABLED=true`,
  - wysylanie wiadomosci do agenta `manfred`, sprawdzanie `.agent_data/<user>/agents/manfred/memory.md` po kazdej wymianie,
  - recznie `curl POST /chat/sessions/<id>/summarize`,
  - sprawdzenie `Session` rekordu w SQLite po obserwacji.

## Rollout / Backward Compatibility

- `OBSERVATIONAL_MEMORY_ENABLED=false` default na prod podczas pierwszego deploya,
- migracja Alembic jest forward-only ale nieblokujaca (kolumny nullable),
- bez memory.md (np. w istniejacych workspaces) agent dziala identycznie jak dzisiaj,
- mozliwosc rollbacku flag-em w razie problemow produkcyjnych.

## Handoff: planner

Done:
- Zdefiniowano kontrakt backend dla observational memory.
- Plan migracji Alembic, modulu `app/services/memory/`, eventow i subscriberow.
- Plan modyfikacji `Runner._build_provider_request`.
- Plan endpointu `/summarize`.

Contract:
- Backend exponuje `POST /chat/sessions/{id}/summarize` z semantyka 202/204/404/503.
- Backend emituje eventy `observation.started/success/failure` i `reflection.started/success` przez SSE.
- `Item.type=OBSERVATION` z polem `state` zwracany w `GET /chat/sessions/{id}`.

Next role:
- developer backendowy implementujacy PR1.

Risks:
- Synchroniczny EventBus - schedule do background tasks musi byc poprawnie zaimplementowany.
- SQLite enum migracja wymaga batch_alter_table.
- Race conditions miedzy agentem piszacym do memory.md przez tools a observerem - akceptowalne na MVP, monitorowac.
