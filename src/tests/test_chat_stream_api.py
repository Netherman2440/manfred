import json

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.requests import Request

from app.api.v1.chat.api import cancel, chat
from app.api.v1.chat.schema import ChatResponse, ChatStreamSessionEvent
from app.providers import ProviderDoneEvent, ProviderErrorEvent, ProviderTextDeltaEvent, ProviderTextDoneEvent
from app.providers.types import ProviderResponse, ProviderTextOutputItem
from app.services.chat_service import ChatServiceNotFoundError


class FakeChatService:
    def __init__(self, events) -> None:  # noqa: ANN001
        self._events = events
        self.close_calls = 0

    async def process_chat_stream(self, payload, *, attachments=None):  # noqa: ANN001
        del payload
        del attachments
        for event in self._events:
            yield event

    async def process_chat(self, payload, *, attachments=None):  # noqa: ANN001
        del payload
        del attachments
        raise AssertionError("Non-stream path should not be used in this test.")

    async def process_cancel(self, session_id, include_tool_result=False):  # noqa: ANN001
        del include_tool_result
        if session_id == "missing-session":
            raise ChatServiceNotFoundError("Session not found: missing-session")
        return ChatResponse(
            id="agent-1",
            agent_id="agent-1",
            session_id=session_id,
            status="cancelled",
            model="openrouter:test-model",
            output=[],
            waiting_for=[],
            error=None,
        )

    def close(self) -> None:
        self.close_calls += 1


async def _read_stream_body(response: StreamingResponse) -> str:
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(chunk)
    return "".join(chunks)


def _build_json_request(payload: dict[str, object]) -> Request:
    body = json.dumps(payload).encode("utf-8")

    async def receive() -> dict[str, object]:
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/chat/completions",
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive,
    )


@pytest.mark.asyncio
async def test_chat_stream_returns_sse_payloads() -> None:
    chat_service = FakeChatService(
        [
            ChatStreamSessionEvent(session_id="session-1", agent_id="agent-1"),
            ProviderTextDeltaEvent(delta="Hello"),
            ProviderTextDoneEvent(text="Hello"),
            ProviderDoneEvent(
                response=ProviderResponse(output=[ProviderTextOutputItem(text="Hello")])
            ),
        ]
    )

    response = await chat(
        _build_json_request(
            {
                "input": [{"type": "message", "role": "user", "content": "Hi"}],
                "stream": True,
            }
        ),
        chat_service=chat_service,
    )

    assert isinstance(response, StreamingResponse)
    body = await _read_stream_body(response)

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["connection"] == "keep-alive"
    assert "event: session" in body
    assert 'data: {"type": "session", "session_id": "session-1", "agent_id": "agent-1"}' in body
    assert "event: text_delta" in body
    assert 'data: {"type": "text_delta", "delta": "Hello"}' in body
    assert "event: done" in body
    done_payload = json.dumps(
        {
            "type": "done",
            "response": {
                "id": None,
                "model": None,
                "output": [{"type": "text", "text": "Hello"}],
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cached_tokens": 0,
                },
                "finish_reason": None,
            },
        },
        ensure_ascii=True,
    )
    assert f"data: {done_payload}" in body
    assert chat_service.close_calls == 1


@pytest.mark.asyncio
async def test_chat_stream_returns_error_event_payload() -> None:
    chat_service = FakeChatService([ProviderErrorEvent(error="setup failed")])

    response = await chat(
        _build_json_request(
            {
                "input": [{"type": "message", "role": "user", "content": "Hi"}],
                "stream": True,
            }
        ),
        chat_service=chat_service,
    )

    assert isinstance(response, StreamingResponse)
    body = await _read_stream_body(response)

    assert "event: error" in body
    assert 'data: {"type": "error", "error": "setup failed", "code": null}' in body
    assert chat_service.close_calls == 1


@pytest.mark.asyncio
async def test_cancel_returns_chat_response() -> None:
    chat_service = FakeChatService([])

    response = await cancel("session-1", chat_service=chat_service)

    assert response.status == "cancelled"
    assert response.session_id == "session-1"
    assert chat_service.close_calls == 1


@pytest.mark.asyncio
async def test_cancel_returns_404_for_missing_session() -> None:
    chat_service = FakeChatService([])

    with pytest.raises(HTTPException) as exc_info:
        await cancel("missing-session", chat_service=chat_service)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Session not found: missing-session"
    assert chat_service.close_calls == 1
