from __future__ import annotations

from typing import Any

from app.domain import FunctionToolDefinition, Tool, ToolExecutionContext
from app.filesystem import AgentFilesystemService, FilesystemSubject, FilesystemWriteRequest
from app.tools.definitions.filesystem.common import run_filesystem_action


WRITE_FILE_PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Path relative to workspace root '.agent_data', for example "
                "'agents/new.agent.md' or 'shared/docs/spec.md'. Do not start with '/'."
            ),
        },
        "operation": {"type": "string", "enum": ["create", "update"]},
        "content": {"type": "string"},
        "action": {"type": "string", "enum": ["replace", "insert_before", "insert_after", "delete_lines"]},
        "lines": {"description": "Optional line selector, for example '10-20'."},
        "checksum": {"type": "string"},
        "dryRun": {"type": "boolean"},
        "createDirs": {"type": "boolean"},
    },
    "required": ["path", "operation"],
    "additionalProperties": False,
}


def build_write_file_tool(filesystem_service: AgentFilesystemService) -> Tool:
    async def handle_write_file(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
        async def action(subject: FilesystemSubject, tool_name: str) -> dict[str, Any]:
            return await filesystem_service.write(
                FilesystemWriteRequest(
                    subject=subject,
                    tool_name=tool_name,
                    path=str(args.get("path", "")),
                    operation=str(args.get("operation", "update")),
                    content=args.get("content"),
                    action=str(args.get("action", "replace")),
                    lines=args.get("lines"),
                    checksum=args.get("checksum"),
                    dry_run=bool(args.get("dryRun", False)),
                    create_dirs=bool(args.get("createDirs", False)),
                )
            )

        return await run_filesystem_action(context=context, action=action)

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="write_file",
            description=(
                "Create or update files inside the workspace. Paths are relative to workspace root "
                "'.agent_data', for example 'agents/new.agent.md' or 'shared/docs/spec.md'."
            ),
            parameters=WRITE_FILE_PARAMETERS,
        ),
        handler=handle_write_file,
    )
