"""Tests for the CLI HTTP/SSE client wire parsing."""

from __future__ import annotations

import httpx
import pytest

from app.cli.client import ManfredClient, ManfredClientError

_SSE_BODY = (
    "event: session\n"
    'data: {"type": "session", "session_id": "s1", "agent_id": "a1"}\n'
    "\n"
    "event: text_delta\n"
    'data: {"type": "text_delta", "delta": "Hi"}\n'
    "\n"
    ": keep-alive comment\n"
    "event: tool.completed\n"
    'data: {"type": "tool.completed", "call_id": "c1", "name": "calculator", "output": {"output": "4"}}\n'
    "\n"
    "event: agent.completed\n"
    'data: {"type": "agent.completed", "agent_id": "a1"}\n'
    "\n"
)


def _client_with(handler) -> ManfredClient:  # noqa: ANN001
    client = ManfredClient("http://test")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.asyncio
async def test_stream_sse_parses_events_in_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/chat/completions"
        return httpx.Response(200, text=_SSE_BODY, headers={"content-type": "text/event-stream"})

    client = _client_with(handler)
    events = [e async for e in client.stream_chat(message="hi")]
    await client.aclose()

    assert [e.event for e in events] == [
        "session",
        "text_delta",
        "tool.completed",
        "agent.completed",
    ]
    assert events[0].data["session_id"] == "s1"
    assert events[2].data["output"] == {"output": "4"}


@pytest.mark.asyncio
async def test_stream_chat_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    client = _client_with(handler)
    with pytest.raises(ManfredClientError) as exc:
        _ = [e async for e in client.stream_chat(message="hi")]
    await client.aclose()
    assert "500" in str(exc.value)


@pytest.mark.asyncio
async def test_deliver_posts_and_returns_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = request.url.query.decode()
        return httpx.Response(
            200,
            json={"status": "completed", "output": [], "waiting_for": [], "agent_id": "a1"},
        )

    client = _client_with(handler)
    result = await client.deliver("a1", call_id="c1", output="blue")
    await client.aclose()

    assert captured["path"] == "/api/v1/chat/agents/a1/deliver"
    assert "include_tool_result=true" in captured["query"]
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_health_false_when_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = _client_with(handler)
    assert await client.health() is False
    await client.aclose()
