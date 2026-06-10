# Task: Manfred Terminal Client (+ SSE streaming fix)

Status: implemented — Parts A, B & C; tests green (181). Live TUI-vs-real-LLM
run not performed (needs an OpenRouter key); launcher boot path verified
end-to-end (migrate + spawn + health + seed).
Branch: `feat/terminal-cli`

## Part C — `manfred` one-command launcher

`app/cli/launcher.py` + `install.sh`. `install.sh` runs `uv sync`
and writes a `~/.local/bin/manfred` shim → `cd REPO/src && exec .venv/bin/python
-m app.cli.launcher`. Tier 1 (personal, repo present); no standalone binary.

Launcher flow: ensure `~/.manfred/` (db, agent_data, .env, logs); resolve the
OpenRouter key (env → app-home .env → prompt once, stored chmod 600); if a
backend is already healthy on the URL → attach the TUI; else run alembic
programmatically against the app-home DB (`alembic.ini` hardcodes the URL, so
override via `set_main_option`), spawn `python -m app.main` (cwd=REPO/src) with
absolute `DATABASE_URL`/`WORKSPACE_PATH`, `MCP_CONFIG_PATH`=nonexistent (MCP
off — native fs tools suffice), logs → `~/.manfred/logs/backend.log`, poll
`/health` ≤30s, launch the TUI, SIGTERM the child on exit (only if we spawned).

Verified end-to-end against a spare port: migrations applied to the app-home
DB, backend boots healthy with no key + MCP off, `/users/me` seeds the manfred
agent into `~/.manfred/agent_data`, clean shutdown. Untested: interactive TUI
launch + the shim (hard to drive headlessly).

## How to run

```bash
# backend (one terminal)
cd manfred_backend/src && uv run python -m app.main      # :3000

# terminal client (another terminal)
cd manfred_backend/src && uv sync
uv run python -m app.cli                     # or --url / --agent
```

## What landed

- `app/runtime/stream_events.py` — runtime stream events + serializer.
- `app/runtime/runner.py` — `run_agent_stream` yields tool results
  (derived from stored `function_call_output` items, deduped by call_id) and
  terminal status events; `event_bus.emit` calls untouched.
- `app/api/v1/chat/api.py` — `_serialize_sse_event` handles runtime events.
- `app/cli/` — `client.py` (httpx + SSE), `app.py` (Textual TUI), `__main__.py`.
- Tests: `test_stream_events.py`, `test_cli_app.py`, runtime-event wire test in
  `test_chat_stream_api.py`; existing runner-event tests updated for new events.
- `textual` + `httpx` added to core `dependencies` in `pyproject.toml`
  (so plain `uv sync` installs them and `manfred` always works).

A Claude-Code-style terminal interface for Manfred, plus the backend SSE
change it depends on. Two self-contained parts. Part A (backend) is a
prerequisite for Part B (CLI).

## Goals

- Scrolling-REPL terminal UI for chatting with Manfred agents, live streaming.
- Fully event-driven: **no polling**. Tool results, status, and `ask_user`
  prompts all arrive over the SSE stream.
- Lives in `src/cli/`, thin HTTP/SSE client against a running backend.

## Non-goals (v1)

- Streaming the internals of delegated child agents (they run via `run_agent`,
  not the streaming path — parent shows the delegate call + final result only).
- Local tool execution / permission prompts (all tools run server-side).
- Multi-user / auth (single-user `default-user`).

---

## Part A — Backend: bridge runtime events onto the SSE stream

### Problem

Today `POST /chat/completions` (stream) emits only `session` + provider events
(`text_delta`, `text_done`, `function_call_delta`, `function_call_done`,
`done`, `error`). Tool **results** and final agent **status/waiting** never hit
the wire. Clients must poll `GET /users/{uid}/sessions/{sid}` to learn them.
This is a gap, not a constraint — the runner already emits the needed data on
the EventBus (`ToolCompletedEvent`, `ToolFailedEvent`, `AgentWaitingEvent`,
`AgentCompletedEvent`, ...).

### Approach (additive, non-breaking)

Add new SSE event types alongside the existing ones. The Flutter parser's
`switch` has a `default:` branch that logs+ignores unknown events
(`chat_repository.dart` ~L547), so adding events does **not** break it.

Bridge mechanism — **no global-bus subscription** (ordering/cross-session
hazards). Instead the runner's streaming path yields runtime events in-order:

- New per-run **sink list** (e.g. `context.stream_sink: list[RunStreamEvent]`),
  appended to at the same points the runner currently calls `event_bus.emit`
  for `tool.completed` / `tool.failed` (inside `handle_turn_response`,
  `runner.py` ~L572–620, ~L555–578, MCP path).
- `run_agent_stream` (`runner.py` ~L243–451) drains+yields the sink after
  each `handle_turn_response(...)` returns. Tool events ordered within the turn.
- Status events (`agent.waiting`, `agent.completed`) already fire at the
  generator level (`runner.py` L423/L432) → yield directly there. Add
  `agent.failed` / `agent.cancelled` at the corresponding `_fail_run` /
  `_cancel_run` return points.
- The existing `event_bus.emit(...)` calls stay (observability unchanged).

### New stream event types

Add to `providers/types.py` (or a new `runtime/stream_events.py`) a
`RunStreamEvent` union = `ProviderStreamEvent` ∪ the below. Serializer in
`api/v1/chat/api.py::_serialize_sse_event` handles them by `.type`.

| `event:` / `type`   | payload fields                                   |
|---------------------|--------------------------------------------------|
| `tool.completed`    | `call_id, name, output (dict), duration_ms`      |
| `tool.failed`       | `call_id, name, error, duration_ms`              |
| `agent.waiting`     | `waiting_for: [{call_id, type, name, description, agent_id}]` |
| `agent.completed`   | `agent_id`                                        |
| `agent.failed`      | `agent_id, error`                                 |
| `agent.cancelled`   | `agent_id`                                        |

### Acceptance (Part A)

- Streaming "calculate 2+2" emits: `session`, text deltas, `function_call_done`
  for calculator, **`tool.completed`** with `output`, then **`agent.completed`**.
- An `ask_user` flow emits **`agent.waiting`** with the `waiting_for` entry
  (call_id + description) and the stream closes.
- Existing events unchanged; existing tests still pass; Flutter unaffected.
- New tests cover each new event type on the stream.

---

## Part B — Terminal CLI client (`src/cli/`)

### Stack

- Python + **Textual** (scrolling `RichLog` + `Input` at bottom). httpx for
  HTTP + SSE (`httpx-sse` or manual line parsing).
- Entry point: `python -m app.cli` (and a `manfred-cli` script).
- Config: `MANFRED_API_URL` env + `--url` flag, default `http://localhost:3000`.

### Data flow (event-driven, no polling)

1. On send: `POST /chat/completions` (`stream=true`), parse SSE.
2. Render by event:
   - `text_delta` → append; `text_done` → re-render that block as markdown.
   - `function_call_done` → render `⚙ name(args)` row.
   - `tool.completed` → attach `→ output` under matching `call_id`.
   - `tool.failed` → attach `✗ error`.
   - `agent.waiting` → enter **answer mode**: show the `description`, capture
     a line, `POST /chat/agents/{agent_id}/deliver` `{call_id, output, is_error:false}`.
   - `agent.completed/failed/cancelled` → finalize turn, re-enable input.
   - `error` → show error, finalize.
3. Mid-run input → `POST /chat/sessions/{sid}/queue`, show `[queued #n]`.

### Features (v1)

- Streaming chat with markdown + tool rows (above).
- `ask_user` / `message` inline answering (deliver).
- Session resume: `/sessions` (list via `GET /users/{uid}/sessions`) →
  `/resume <n>` re-renders transcript from `GET /users/{uid}/sessions/{sid}`.
- Agent select/switch: `/agent [name]` (list via `GET /agents`), startup pick.
- Attachments: `@./path` inline → strip from text, multipart upload.
- `/summarize` → `POST /chat/sessions/{sid}/summarize`.
- Commands: `/new /quit /clear /help /cancel /sessions /resume /agent /model /summarize`.
- `/cancel` or Esc → `POST /chat/sessions/{sid}/cancel`.

### Acceptance (Part B)

- Can start, send a message, see streamed text + a tool call with its result.
- Can answer an `ask_user` prompt and see the run continue.
- Can list + resume a prior session and continue it.
- Can switch agent; can send an attachment with `@path`.
- Backend down → friendly message, not a stack trace.

---

## Implementation order

1. Part A: new event types + serializer + runner sink + status yields.
2. Part A tests (stream emits new events).
3. Part B: CLI skeleton (connect, stream, render text).
4. Part B: tool rows, waiting/deliver, commands, sessions, agents, attachments.
5. End-to-end verify against a running backend.
