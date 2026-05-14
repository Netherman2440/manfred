from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

MCP_TOOL_SEPARATOR = "__"
McpServerStatus = Literal["connected", "disconnected"]


@dataclass(slots=True, frozen=True)
class McpServerConfig:
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    transport: Literal["stdio"] = "stdio"


@dataclass(slots=True, frozen=True)
class McpConfig:
    mcp_servers: dict[str, McpServerConfig] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class McpToolInfo:
    server: str
    original_name: str
    prefixed_name: str
    description: str
    input_schema: dict[str, Any]


class McpManager(Protocol):
    async def start(self) -> None: ...

    async def close(self) -> None: ...

    def servers(self) -> list[str]: ...

    def server_status(self, name: str) -> McpServerStatus: ...

    def parse_name(self, prefixed_name: str) -> tuple[str, str] | None: ...

    def list_tools(self) -> list[McpToolInfo]: ...

    def list_server_tools(self, server_name: str) -> list[McpToolInfo]: ...

    def get_tool(self, prefixed_name: str) -> McpToolInfo | None: ...

    async def call_tool(
        self,
        prefixed_name: str,
        arguments: dict[str, Any],
        signal: object | None = None,
    ) -> str: ...


def parse_mcp_tool_name(prefixed_name: str) -> tuple[str, str] | None:
    if not prefixed_name or MCP_TOOL_SEPARATOR not in prefixed_name:
        return None

    server, tool_name = prefixed_name.split(MCP_TOOL_SEPARATOR, 1)
    if not server or not tool_name:
        return None
    return server, tool_name
