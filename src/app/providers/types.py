from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.tool import ToolDefinition


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


ProviderInputItem = (
    ProviderMessageInputItem
    | ProviderFunctionCallInputItem
    | ProviderFunctionCallOutputInputItem
)


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


@dataclass(slots=True, frozen=True)
class ProviderRequest:
    model: str
    instructions: str
    input: list[ProviderInputItem]
    tools: list[ToolDefinition] = field(default_factory=list)
    temperature: float | None = None


@dataclass(slots=True, frozen=True)
class ProviderResponse:
    output: list[ProviderOutputItem]
    usage: ProviderUsage = field(default_factory=ProviderUsage)
