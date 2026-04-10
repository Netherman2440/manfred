from pathlib import Path

from app.domain import FunctionToolDefinition, WebSearchToolDefinition
from app.mcp import McpToolInfo
from app.services.agent_loader import AgentLoader
from app.tools.registry import ToolRegistry


class FakeMcpManager:
    def __init__(self, tools: list[McpToolInfo]) -> None:
        self._tools = {tool.prefixed_name: tool for tool in tools}

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def servers(self) -> list[str]:
        return []

    def server_status(self, name: str) -> str:
        del name
        return "disconnected"

    def parse_name(self, prefixed_name: str) -> tuple[str, str] | None:
        if "__" not in prefixed_name:
            return None
        server_name, tool_name = prefixed_name.split("__", 1)
        return (server_name, tool_name) if server_name and tool_name else None

    def list_tools(self) -> list[McpToolInfo]:
        return list(self._tools.values())

    def list_server_tools(self, server_name: str) -> list[McpToolInfo]:
        return [tool for tool in self._tools.values() if tool.server == server_name]

    def get_tool(self, prefixed_name: str) -> McpToolInfo | None:
        return self._tools.get(prefixed_name)

    async def call_tool(
        self,
        prefixed_name: str,
        arguments: dict[str, object],
        signal: object | None = None,
    ) -> str:
        del prefixed_name
        del arguments
        del signal
        raise AssertionError("call_tool should not be used in AgentLoader tests")


def test_agent_loader_resolves_web_search_and_mcp_tools() -> None:
    loader = AgentLoader(
        tool_registry=ToolRegistry(tools=[]),
        mcp_manager=FakeMcpManager(
            tools=[
                McpToolInfo(
                    server="files",
                    original_name="fs_read",
                    prefixed_name="files__fs_read",
                    description="Read files from workspace",
                    input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
                )
            ]
        ),
        repo_root=Path("/tmp"),
        workspace_path=".agent_data",
    )

    resolved = loader.resolve_tool_definitions(["web_search", "files__fs_read", "missing_tool"])

    assert isinstance(resolved[0], WebSearchToolDefinition)
    assert isinstance(resolved[1], FunctionToolDefinition)
    assert resolved[1].name == "files__fs_read"
    assert resolved[1].description == "Read files from workspace"
    assert resolved[1].parameters == {"type": "object", "properties": {"path": {"type": "string"}}}
