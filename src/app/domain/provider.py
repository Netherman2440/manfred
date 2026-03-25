from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeAlias, runtime_checkable

from app.domain.tool import FunctionToolDefinition


@dataclass(slots=True, frozen=True)
class ProviderMessageInput:
    role: Literal["user", "assistant", "system"]
    content: str
    type: Literal["message"] = "message"


@dataclass(slots=True, frozen=True)
class ProviderFunctionCallInput:
    call_id: str
    name: str
    arguments: dict[str, Any]
    type: Literal["function_call"] = "function_call"


@dataclass(slots=True, frozen=True)
class ProviderFunctionResultInput:
    call_id: str
    name: str
    output: Any
    is_error: bool = False
    type: Literal["function_result"] = "function_result"


ProviderInputItem: TypeAlias = (
    ProviderMessageInput
    | ProviderFunctionCallInput
    | ProviderFunctionResultInput
)


@dataclass(slots=True, frozen=True)
class ProviderInput:
    model: str
    instructions: str
    items: list[ProviderInputItem] = field(default_factory=list)
    tools: list[FunctionToolDefinition] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class ProviderTextOutput:
    text: str
    type: Literal["text"] = "text"


@dataclass(slots=True, frozen=True)
class ProviderFunctionCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
    type: Literal["function_call"] = "function_call"


ProviderOutputItem: TypeAlias = ProviderTextOutput | ProviderFunctionCall


@dataclass(slots=True, frozen=True)
class ProviderResponse:
    model: str | None = None
    output: list[ProviderOutputItem] = field(default_factory=list)


@runtime_checkable
class Provider(Protocol):
    def generate(self, provider_input: ProviderInput) -> ProviderResponse:
        ...
