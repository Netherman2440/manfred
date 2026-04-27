from __future__ import annotations

from typing import Any

from app.domain import FunctionToolDefinition, Tool, ToolExecutionContext
from app.filesystem import AgentFilesystemService, FilesystemReadRequest, FilesystemSubject
from app.tools.definitions.filesystem.common import run_filesystem_action


READ_FILE_PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Path relative to workspace root '.agent_data', for example "
                "'agents/manfred.agent.md' or 'shared/docs/spec.md'. Do not start with '/'."
            ),
        },
        "mode": {"type": "string", "enum": ["auto", "tree", "list", "content"]},
        "lines": {"description": "Optional line selector, for example '10-20'."},
        "depth": {"type": "integer", "minimum": 1},
        "limit": {"type": "integer", "minimum": 1},
        "offset": {"type": "integer", "minimum": 0},
        "details": {"type": "boolean"},
        "types": {"type": "array", "items": {"type": "string"}},
        "glob": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
        "exclude": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
        "respectIgnore": {"type": "boolean"},
    },
    "required": ["path"],
    "additionalProperties": False,
}


def build_read_file_tool(filesystem_service: AgentFilesystemService) -> Tool:
    async def handle_read_file(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
        async def action(subject: FilesystemSubject, tool_name: str) -> dict[str, Any]:
            return await filesystem_service.read(
                FilesystemReadRequest(
                    subject=subject,
                    tool_name=tool_name,
                    path=str(args.get("path", ".")),
                    mode=str(args.get("mode", "auto")),
                    lines=args.get("lines"),
                    depth=int(args.get("depth", 2)),
                    limit=int(args.get("limit", 200)),
                    offset=int(args.get("offset", 0)),
                    details=bool(args.get("details", False)),
                    types=_string_list(args.get("types")),
                    glob=args.get("glob"),
                    exclude=args.get("exclude"),
                    respect_ignore=bool(args.get("respectIgnore", True)),
                )
            )

        return await run_filesystem_action(context=context, action=action)

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="read_file",
            description=(
                "Read file contents or inspect directories inside the workspace. "
                "Paths are relative to workspace root '.agent_data', for example "
                "'agents/manfred.agent.md' or 'shared/docs/spec.md'."
            ),
            parameters=READ_FILE_PARAMETERS,
        ),
        handler=handle_read_file,
    )


def _string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]
