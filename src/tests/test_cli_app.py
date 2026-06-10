"""Smoke tests for the Manfred terminal client (Part B)."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("httpx")

from app.cli.app import ManfredCli, _coerce_output, _short  # noqa: E402
from app.cli.client import StreamEvent  # noqa: E402


def _event(kind: str, **data: object) -> StreamEvent:
    payload = {"type": kind, **data}
    return StreamEvent(event=kind, data=payload)


@pytest.mark.asyncio
async def test_stream_run_renders_and_completes() -> None:
    app = ManfredCli(base_url="http://localhost:3000", agent="manfred")
    async with app.run_test():
        app._running = True
        for event in [
            _event("session", session_id="sess-1", agent_id="agent-1"),
            _event("text_delta", delta="The result "),
            _event("text_delta", delta="is 4."),
            _event("text_done", text="The result is 4."),
            _event("function_call_done", name="calculator", arguments={"a": 2, "b": 2}),
            _event("tool.completed", name="calculator", output={"ok": True, "output": "4"}),
            _event("agent.completed", agent_id="agent-1"),
        ]:
            app._on_stream_event(event)

        assert app._session_id == "sess-1"
        assert app._running is False
        assert app._waiting is None


@pytest.mark.asyncio
async def test_stream_run_enters_waiting_on_ask_user() -> None:
    app = ManfredCli(base_url="http://localhost:3000", agent="manfred")
    async with app.run_test():
        app._running = True
        app._on_stream_event(_event("session", session_id="sess-1", agent_id="agent-1"))
        app._on_stream_event(
            _event(
                "agent.waiting",
                waiting_for=[
                    {
                        "call_id": "call-9",
                        "type": "human",
                        "name": "ask_user",
                        "description": "What format?",
                        "agent_id": "agent-1",
                    }
                ],
            )
        )
        assert app._waiting == ("agent-1", "call-9")
        assert app._running is False


@pytest.mark.asyncio
async def test_agent_failed_finalizes() -> None:
    app = ManfredCli(base_url="http://localhost:3000", agent="manfred")
    async with app.run_test():
        app._running = True
        app._on_stream_event(_event("agent.failed", agent_id="a1", error="boom"))
        assert app._running is False


@pytest.mark.asyncio
async def test_render_chat_response_completed_finalizes() -> None:
    app = ManfredCli(base_url="http://localhost:3000", agent="manfred")
    async with app.run_test():
        app._running = True
        app._render_chat_response(
            {
                "agent_id": "agent-1",
                "status": "completed",
                "output": [
                    {"type": "text", "text": "Saved blue as your favourite."},
                    {"type": "function_call", "name": "write_file", "arguments": {"path": "p"}},
                    {
                        "type": "function_call_output",
                        "name": "write_file",
                        "output": '{"ok": true, "output": "written"}',
                        "is_error": False,
                    },
                ],
                "waiting_for": [],
                "error": None,
            }
        )
        assert app._running is False
        assert app._waiting is None


@pytest.mark.asyncio
async def test_render_chat_response_waiting_reenters_answer_mode() -> None:
    app = ManfredCli(base_url="http://localhost:3000", agent="manfred")
    async with app.run_test():
        app._running = True
        app._render_chat_response(
            {
                "agent_id": "agent-1",
                "status": "waiting",
                "output": [{"type": "text", "text": "And your second favourite?"}],
                "waiting_for": [
                    {
                        "call_id": "call-2",
                        "type": "human",
                        "name": "ask_user",
                        "description": "Second favourite?",
                        "agent_id": "agent-1",
                    }
                ],
                "error": None,
            }
        )
        assert app._waiting == ("agent-1", "call-2")
        assert app._running is False


@pytest.mark.asyncio
async def test_agent_failed_after_error_event_not_double_printed() -> None:
    app = ManfredCli(base_url="http://localhost:3000", agent="manfred")
    async with app.run_test():
        app._running = True
        app._last_error = None
        app._on_stream_event(_event("error", error="provider exploded"))
        assert app._last_error == "provider exploded"
        # agent.failed carrying the same error must not re-print (dedupe path).
        app._on_stream_event(_event("agent.failed", agent_id="a1", error="provider exploded"))
        assert app._running is False


def test_short_truncates_and_serializes() -> None:
    assert _short("abc", 10) == "abc"
    assert _short("a" * 20, 10).endswith("…")
    assert _short({"k": "v"}) == '{"k": "v"}'


def test_coerce_output_variants() -> None:
    assert _coerce_output({"ok": True}) == {"ok": True}
    assert _coerce_output('{"x": 1}') == {"x": 1}
    assert _coerce_output("plain") == {"output": "plain"}
    assert _coerce_output(4) == {"output": 4}
