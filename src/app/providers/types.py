from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.domain.tool import ToolDefinition

if TYPE_CHECKING:
    from app.runtime.cancellation import CancellationSignal


@dataclass(slots=True, frozen=True)
class ProviderMessageInputItem:
    role: str
    content: str
    type: str = "message"


@dataclass(slots=True, frozen=True)
class ProviderFunctionCallInputItem:
    call_id: str
    name: str
    arguments: dict[str, Any]
    type: str = "function_call"


@dataclass(slots=True, frozen=True)
class ProviderFunctionCallOutputInputItem:
    call_id: str
    name: str
    output: str
    type: str = "function_call_output"


ProviderInputItem = ProviderMessageInputItem | ProviderFunctionCallInputItem | ProviderFunctionCallOutputInputItem


@dataclass(slots=True, frozen=True)
class ProviderTextOutputItem:
    text: str
    type: str = "text"


@dataclass(slots=True, frozen=True)
class ProviderFunctionCallOutputItem:
    call_id: str
    name: str
    arguments: dict[str, Any]
    type: str = "function_call"


ProviderOutputItem = ProviderTextOutputItem | ProviderFunctionCallOutputItem


@dataclass(slots=True, frozen=True)
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0


@dataclass(slots=True, frozen=True)
class ProviderRequest:
    model: str
    instructions: str
    input: list[ProviderInputItem]
    tools: list[ToolDefinition] = field(default_factory=list)
    temperature: float | None = None
    signal: CancellationSignal | None = None


@dataclass(slots=True, frozen=True)
class ProviderResponse:
    output: list[ProviderOutputItem]
    id: str | None = None
    model: str | None = None
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    finish_reason: str | None = None


@dataclass(slots=True, frozen=True)
class ProviderTextDeltaEvent:
    delta: str
    type: str = "text_delta"


@dataclass(slots=True, frozen=True)
class ProviderTextDoneEvent:
    text: str
    type: str = "text_done"


@dataclass(slots=True, frozen=True)
class ProviderFunctionCallDeltaEvent:
    call_id: str
    name: str
    arguments_delta: str
    type: str = "function_call_delta"


@dataclass(slots=True, frozen=True)
class ProviderFunctionCallDoneEvent:
    call_id: str
    name: str
    arguments: dict[str, Any]
    type: str = "function_call_done"


@dataclass(slots=True, frozen=True)
class ProviderDoneEvent:
    response: ProviderResponse
    type: str = "done"


@dataclass(slots=True, frozen=True)
class ProviderErrorEvent:
    error: str
    code: str | None = None
    type: str = "error"


ProviderStreamEvent = (
    ProviderTextDeltaEvent
    | ProviderTextDoneEvent
    | ProviderFunctionCallDeltaEvent
    | ProviderFunctionCallDoneEvent
    | ProviderDoneEvent
    | ProviderErrorEvent
)


def serialize_provider_output_item(item: ProviderOutputItem) -> dict[str, Any]:
    if isinstance(item, ProviderTextOutputItem):
        return {
            "type": item.type,
            "text": item.text,
        }

    return {
        "type": item.type,
        "call_id": item.call_id,
        "name": item.name,
        "arguments": item.arguments,
    }


def serialize_provider_usage(usage: ProviderUsage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "cached_tokens": usage.cached_tokens,
    }


def serialize_provider_response(response: ProviderResponse) -> dict[str, Any]:
    return {
        "id": response.id,
        "model": response.model,
        "output": [serialize_provider_output_item(item) for item in response.output],
        "usage": serialize_provider_usage(response.usage),
        "finish_reason": response.finish_reason,
    }


def serialize_provider_stream_event(event: ProviderStreamEvent) -> dict[str, Any]:
    if isinstance(event, ProviderTextDeltaEvent):
        return {
            "type": event.type,
            "delta": event.delta,
        }

    if isinstance(event, ProviderTextDoneEvent):
        return {
            "type": event.type,
            "text": event.text,
        }

    if isinstance(event, ProviderFunctionCallDeltaEvent):
        return {
            "type": event.type,
            "call_id": event.call_id,
            "name": event.name,
            "arguments_delta": event.arguments_delta,
        }

    if isinstance(event, ProviderFunctionCallDoneEvent):
        return {
            "type": event.type,
            "call_id": event.call_id,
            "name": event.name,
            "arguments": event.arguments,
        }

    if isinstance(event, ProviderDoneEvent):
        return {
            "type": event.type,
            "response": serialize_provider_response(event.response),
        }

    return {
        "type": event.type,
        "error": event.error,
        "code": event.code,
    }
