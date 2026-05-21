from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

if TYPE_CHECKING:
    from app.runtime.cancellation import CancellationSignal


@dataclass(slots=True, frozen=True)
class FunctionToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    type: Literal["function"] = "function"


SearchContextSize: TypeAlias = Literal["low", "medium", "high"]


@dataclass(slots=True, frozen=True)
class WebSearchToolDefinition:
    name: Literal["web_search"] = "web_search"
    type: Literal["web_search"] = "web_search"
    engine: str = "exa"
    max_results: int = 5
    max_total_results: int = 20
    search_context_size: SearchContextSize = "medium"
    allowed_domains: tuple[str, ...] = ("wikipedia.org", "hub.ag3nts.org")
    excluded_domains: tuple[str, ...] = ("reddit.com",)


ToolDefinition: TypeAlias = FunctionToolDefinition | WebSearchToolDefinition
ToolType: TypeAlias = Literal["sync", "async", "agent", "human"]
ToolResult: TypeAlias = dict[str, bool | str]


@dataclass(slots=True, frozen=True)
class ToolExecutionContext:
    user_id: str | None
    session_id: str
    agent_id: str
    call_id: str
    tool_name: str
    user_name: str | None = None
    workspace_path: str | None = None
    signal: CancellationSignal | None = None


ToolHandler: TypeAlias = Callable[[dict[str, Any], ToolExecutionContext], Awaitable[ToolResult]]


@dataclass(slots=True, frozen=True)
class Tool:
    type: ToolType
    definition: ToolDefinition
    handler: ToolHandler
