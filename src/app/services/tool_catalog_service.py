from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain import FunctionToolDefinition
from app.mcp import McpManager
from app.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class ToolSummary:
    name: str
    description: str | None
    type: Literal["function", "web_search", "mcp"]


class ToolCatalogService:
    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        mcp_manager: McpManager,
    ) -> None:
        self.tool_registry = tool_registry
        self.mcp_manager = mcp_manager

    def list_tools(self) -> list[ToolSummary]:
        """Return all available tools: function tools from registry + web_search + MCP."""
        results: list[ToolSummary] = []

        # 1. Function tools from the registry
        for tool in self.tool_registry.list():
            if isinstance(tool, FunctionToolDefinition):
                results.append(
                    ToolSummary(
                        name=tool.name,
                        description=tool.description,
                        type="function",
                    )
                )

        # 2. web_search special tool
        results.append(
            ToolSummary(
                name="web_search",
                description="Search the web",
                type="web_search",
            )
        )

        # 3. MCP tools
        for mcp_tool in self.mcp_manager.list_tools():
            results.append(
                ToolSummary(
                    name=mcp_tool.prefixed_name,
                    description=mcp_tool.description,
                    type="mcp",
                )
            )

        # Deterministic sort: (type, name) with function < web_search < mcp
        _type_order = {"function": 0, "web_search": 1, "mcp": 2}
        results.sort(key=lambda t: (_type_order[t.type], t.name))
        return results

    def known_tool_names(self) -> set[str]:
        """Return set of all valid tool names for validation."""
        return {tool.name for tool in self.list_tools()}
