from __future__ import annotations

import json
from pathlib import Path

from app.mcp.types import McpConfig, McpServerConfig


def load_mcp_config(config_path: Path) -> McpConfig:
    if not config_path.exists():
        return McpConfig()

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse MCP config at {config_path}: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"MCP config at {config_path} must be a JSON object.")

    raw_servers = payload.get("mcpServers", {})
    if raw_servers is None:
        raw_servers = {}
    if not isinstance(raw_servers, dict):
        raise ValueError(f"MCP config at {config_path} has invalid 'mcpServers' section.")

    servers: dict[str, McpServerConfig] = {}
    for server_name, raw_config in raw_servers.items():
        if not isinstance(server_name, str) or not server_name.strip():
            raise ValueError(f"MCP config at {config_path} contains an invalid server name.")
        if not isinstance(raw_config, dict):
            raise ValueError(f"MCP server '{server_name}' must be a JSON object.")

        transport = raw_config.get("transport", "stdio")
        if transport != "stdio":
            raise ValueError(
                f"MCP server '{server_name}' uses unsupported transport '{transport}'. Only 'stdio' is supported."
            )

        command = raw_config.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"MCP server '{server_name}' must define a non-empty 'command'.")

        raw_args = raw_config.get("args", [])
        if not isinstance(raw_args, list) or any(not isinstance(item, str) for item in raw_args):
            raise ValueError(f"MCP server '{server_name}' has invalid 'args'.")

        raw_env = raw_config.get("env", {})
        if raw_env is None:
            raw_env = {}
        if not isinstance(raw_env, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in raw_env.items()
        ):
            raise ValueError(f"MCP server '{server_name}' has invalid 'env'.")

        cwd = raw_config.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError(f"MCP server '{server_name}' has invalid 'cwd'.")

        servers[server_name] = McpServerConfig(
            transport="stdio",
            command=command,
            args=list(raw_args),
            env=dict(raw_env),
            cwd=cwd,
        )

    return McpConfig(mcp_servers=servers)
