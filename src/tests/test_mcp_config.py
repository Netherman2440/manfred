import json
from pathlib import Path

import pytest

from app.mcp import load_mcp_config, parse_mcp_tool_name


def test_load_mcp_config_returns_empty_when_file_missing(tmp_path: Path) -> None:
    config = load_mcp_config(tmp_path / ".mcp.json")

    assert config.mcp_servers == {}


def test_load_mcp_config_parses_stdio_servers(tmp_path: Path) -> None:
    config_path = tmp_path / ".mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "files": {
                        "command": "node",
                        "args": ["dist/index.js"],
                        "env": {"FS_ROOTS": "/tmp"},
                        "cwd": "/workspace",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_mcp_config(config_path)

    assert sorted(config.mcp_servers) == ["files"]
    assert config.mcp_servers["files"].command == "node"
    assert config.mcp_servers["files"].args == ["dist/index.js"]
    assert config.mcp_servers["files"].env == {"FS_ROOTS": "/tmp"}
    assert config.mcp_servers["files"].cwd == "/workspace"


def test_load_mcp_config_raises_on_invalid_json(tmp_path: Path) -> None:
    config_path = tmp_path / ".mcp.json"
    config_path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="Failed to parse MCP config"):
        load_mcp_config(config_path)


def test_parse_mcp_tool_name_handles_prefixed_names() -> None:
    assert parse_mcp_tool_name("files__fs_read") == ("files", "fs_read")
    assert parse_mcp_tool_name("files") is None
    assert parse_mcp_tool_name("__fs_read") is None
