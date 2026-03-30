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


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools: self.register(self, tool)

    def register(self, tool: Tool) -> None:
        self._tools[tool.definition.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[ToolDefinition]:
        return [tool.definition for tool in self._tools.values()]

    def list_by_name(self, names: Iterable[str]) -> list[ToolDefinition]:
        resolved: list[ToolDefinition] = []
        for name in names:
            tool = self._tools.get(name)
            if tool is not None:
                resolved.append(tool.definition)
        return resolved

    async def execute(self, name: str, args: dict[str, Any], signal: Any | None = None) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"Tool not found: {name}"}

        try:
            return await tool.handler(args, signal)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc) or "Tool execution failed"}
