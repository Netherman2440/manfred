from __future__ import annotations

from app.domain.tool import Tool, ToolDefinition, ToolResult
from typing import Any, Iterable



class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        name = getattr(tool.definition, "name", None)
        if not name:
            raise ValueError("Tool definition must expose a name")
        self._tools[name] = tool

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
        except Exception as exc:
            return {"ok": False, "error": str(exc) or "Tool execution failed"}
