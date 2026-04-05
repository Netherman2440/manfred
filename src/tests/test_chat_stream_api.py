import json

import pytest
from fastapi.responses import StreamingResponse

from app.api.v1.chat.api import chat
from app.api.v1.chat.schema import ChatRequest, MessageInputItem
from app.providers import ProviderDoneEvent, ProviderErrorEvent, ProviderTextDeltaEvent, ProviderTextDoneEvent
from app.providers.types import ProviderResponse, ProviderTextOutputItem


class FakeChatService:
    def __init__(self, events) -> None:  # noqa: ANN001
        self._events = events
        self.close_calls = 0

    async def process_chat_stream(self, payload):  # noqa: ANN001
        del payload
        for event in self._events:
            yield event

    async def process_chat(self, payload):  # noqa: ANN001
        del payload
        raise AssertionError("Non-stream path should not be used in this test.")

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


@pytest.mark.asyncio
async def test_chat_stream_returns_sse_payloads() -> None:
    chat_service = FakeChatService(
        [
            ProviderTextDeltaEvent(delta="Hello"),
            ProviderTextDoneEvent(text="Hello"),
            ProviderDoneEvent(
                response=ProviderResponse(output=[ProviderTextOutputItem(text="Hello")])
            ),
        ]
    )

    response = await chat(
        ChatRequest(
            input=[MessageInputItem(role="user", content="Hi")],
            stream=True,
        ),
        chat_service=chat_service,
    )

    assert isinstance(response, StreamingResponse)
    body = await _read_stream_body(response)

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["connection"] == "keep-alive"
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
        ChatRequest(
            input=[MessageInputItem(role="user", content="Hi")],
            stream=True,
        ),
        chat_service=chat_service,
    )

    assert isinstance(response, StreamingResponse)
    body = await _read_stream_body(response)

    assert "event: error" in body
    assert 'data: {"type": "error", "error": "setup failed", "code": null}' in body
    assert chat_service.close_calls == 1
