# Stream tool lifecycle over SSE — backend

## Goal

Yield `tool.called` / `tool.completed` / `tool.failed` events on the `/chat/completions` SSE
stream, for the whole agent tree (incl. delegated sub-agents). The events already exist and are
already emitted on the `EventBus`; today they are never yielded to the stream.

## Changes

### 1. Bridge EventBus tool events into the stream (`runtime/runner.py`, `run_agent_stream`)

The tool events are emitted from inside `handle_turn_response` (deep in the tool-execution call
tree), which returns a `TurnResult` — it is not a generator, so it cannot yield. Bridge via the
`EventBus`:

- At the top of `run_agent_stream` (after `context` is loaded so `context.trace_id` is known),
  create a per-run buffer `list[BaseEvent]` and a handler that appends an event **only if
  `event.ctx.trace_id == context.trace_id`** (this is what captures child sub-agent frames, which
  share the trace id). Subscribe the handler to `"tool.called"`, `"tool.completed"`,
  `"tool.failed"`.
- **Wrap the entire method body in `try / finally` and unsubscribe in `finally`.** The method has
  many `return` points plus `GeneratorExit` on client disconnect; a leaked handler stays on the
  shared bus forever (memory + per-emit cost leak). This is mandatory.
- **Drain the buffer right after `handle_turn_response` returns** — concretely, right after
  `total_usage = self._add_usage(...)` (~line 398), BEFORE the `cancelled` / `continue` /
  `waiting` / `completed` / `failed` branches that `return`. Draining here guarantees the final
  turn's events (and the `tool.called` for an `ask_user` that goes WAITING) are yielded.
  Pop-consume (clear the buffer) so turn N's events are not re-yielded on turn N+1.

The early `return` at the top (agent already WAITING) yields nothing — fine, no tools ran.

### 2. Widen stream return types

`run_agent_stream`, `ChatService.stream_prepared_chat`, `ChatService.process_chat_stream` currently
return `AsyncIterable[ProviderStreamEvent]` (the latter two include `ChatStreamSessionEvent`).
Widen all three to also include the tool events. Add a union alias
`ToolStreamEvent = ToolCalledEvent | ToolCompletedEvent | ToolFailedEvent` in
`events/definitions/__init__.py` and use it in the hints.

### 3. Serialize tool events for SSE (`api/v1/chat/api.py`, `_serialize_sse_event`)

Add a branch handling the three tool events (they are `BaseEvent` subclasses with `.ctx`). Emit
the shapes from the root spec contract:

- common: `type`, `call_id`, `name`, `agent_id = ctx.agent_id`,
  `parent_agent_id = ctx.parent_agent_id`, `depth = ctx.depth`.
- `tool.called`: + `arguments`.
- `tool.completed`: + `duration_ms`, `is_error: false`, `tool_result = event.output`.
- `tool.failed`: + `duration_ms`, `is_error: true`,
  `tool_result = {"ok": false, "error": event.error}`.

Keep the existing SSE framing `event: <type>\ndata: <json>\n\n`. Widen the param type hint.

## Shape parity (load-bearing)

`tool_result` must equal `session_query_service._deserialize_tool_result(item.output)` for the
same call — i.e. the raw stored `result` dict. `ToolCompletedEvent.output` is already
`dict(result)`, so it matches directly. For failures, persistence stores
`{"ok": false, "error": ...}`; mirror that.

## Out of scope

Deliver/resume (`deliver_result`) is non-streaming; human-tool results on resume are returned in
the deliver `ChatResponse`, not over SSE. Do not change this.

## Verify

- `uv run pytest` (focus: chat api / runner / chat_service tests).
- Manual: streaming chat with a sync tool → observe `tool.completed` SSE frame carrying
  `tool_result` before `done`.
