from __future__ import annotations

from typing import Any

from app.domain import FunctionToolDefinition, Tool, ToolExecutionContext
from app.services.filesystem import AgentFilesystemService, FilesystemSubject, FilesystemWriteRequest
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
        "operation": {
            "type": "string",
            "enum": ["create", "update"],
            "description": (
                "'create' — make a new file (fails if it already exists). "
                "'update' — modify an existing file, behavior controlled by 'action'."
            ),
        },
        "content": {
            "type": "string",
            "description": "The text to write or insert. Required for create, append, replace, insert_*.",
        },
        "action": {
            "type": "string",
            "enum": ["append", "replace", "insert_before", "insert_after", "delete_lines"],
            "description": (
                "Only used with operation='update'. Defaults to 'append'. "
                "Choose carefully — this controls how 'content' is applied to the file:\n"
                "- 'append' (default, SAFE): adds 'content' at the END of the file. "
                "Does NOT take 'lines'. Use this for incremental notes, logs, post-mortems, "
                "growing documents.\n"
                "- 'replace': replaces a line range with 'content'. REQUIRES 'lines'. "
                "WITHOUT 'lines' it OVERWRITES THE ENTIRE FILE — only do this when you "
                "really want a full rewrite.\n"
                "- 'insert_before': inserts 'content' before the first line of the range. "
                "Requires 'lines'.\n"
                "- 'insert_after': inserts 'content' after the last line of the range. "
                "Requires 'lines'.\n"
                "- 'delete_lines': removes the line range. Requires 'lines', no 'content'."
            ),
        },
        "lines": {
            "description": (
                "Line range selector for replace / insert_* / delete_lines, "
                "for example '10-20' or '5-5'. Required for those actions. "
                "Must NOT be set with 'append'."
            ),
        },
        "checksum": {
            "type": "string",
            "description": "Optional file checksum guard — write fails if current file checksum differs.",
        },
        "dryRun": {
            "type": "boolean",
            "description": "If true, return a unified diff instead of applying the change.",
        },
        "createDirs": {
            "type": "boolean",
            "description": "If true (for 'create'), create missing parent directories.",
        },
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
                    action=str(args.get("action", "append")),
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
                "'.agent_data', for example 'agents/new.agent.md' or 'shared/docs/spec.md'.\n\n"
                "Two operations:\n"
                "- operation='create' — new file. Pass 'content'. Use 'createDirs' to make parent dirs.\n"
                "- operation='update' — existing file. Default 'action' is 'append' (adds to end). "
                "To rewrite the entire file pass action='replace' WITHOUT 'lines'. To edit a specific "
                "line range pass action='replace'/'insert_before'/'insert_after'/'delete_lines' WITH 'lines'.\n\n"
                "Defaulting to 'append' protects you from accidentally wiping a file — if you forget to "
                "specify 'action' on an update, you'll just add to the bottom instead of overwriting."
            ),
            parameters=WRITE_FILE_PARAMETERS,
        ),
        handler=handle_write_file,
    )
