from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias


@dataclass(slots=True, frozen=True)
class FunctionToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    type: Literal["function"] = "function"


@dataclass(slots=True, frozen=True)
class WebSearchToolDefinition:
    type: Literal["web_search"] = "web_search"


ToolDefinition: TypeAlias = FunctionToolDefinition | WebSearchToolDefinition
ToolType: TypeAlias = Literal["sync", "async", "agent", "human"]
ToolResult: TypeAlias = dict[str, bool | str]
ToolHandler: TypeAlias = Callable[[dict[str, Any], Any | None], Awaitable[ToolResult]]


@dataclass(slots=True, frozen=True)
class Tool:
    type: ToolType
    definition: ToolDefinition
    handler: ToolHandler


