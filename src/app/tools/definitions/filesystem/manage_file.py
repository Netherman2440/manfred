from __future__ import annotations

from typing import Any

from app.domain import FunctionToolDefinition, Tool, ToolExecutionContext
from app.services.filesystem import AgentFilesystemService, FilesystemManageRequest, FilesystemSubject
from app.tools.definitions.filesystem.common import run_filesystem_action


MANAGE_FILE_PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Source path relative to workspace root '.agent_data', for example "
                "'agents/manfred.agent.md' or 'workspaces/u-1/note.md'. Do not start with '/'."
            ),
        },
        "operation": {"type": "string", "enum": ["delete", "rename", "move", "copy", "mkdir", "stat"]},
        "target": {"type": "string"},
        "recursive": {"type": "boolean"},
        "force": {"type": "boolean"},
    },
    "required": ["path", "operation"],
    "additionalProperties": False,
}


def build_manage_file_tool(filesystem_service: AgentFilesystemService) -> Tool:
    async def handle_manage_file(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
        async def action(subject: FilesystemSubject, tool_name: str) -> dict[str, Any]:
            return await filesystem_service.manage(
                FilesystemManageRequest(
                    subject=subject,
                    tool_name=tool_name,
                    path=str(args.get("path", "")),
                    operation=str(args.get("operation", "stat")),
                    target=str(args["target"]) if "target" in args and args.get("target") is not None else None,
                    recursive=bool(args.get("recursive", False)),
                    force=bool(args.get("force", False)),
                )
            )

        return await run_filesystem_action(context=context, action=action)

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="manage_file",
            description=(
                "Manage files and directories inside the workspace. Paths are relative to workspace root "
                "'.agent_data', for example 'agents/...', 'shared/...', or 'workspaces/...'."
            ),
            parameters=MANAGE_FILE_PARAMETERS,
        ),
        handler=handle_manage_file,
    )
