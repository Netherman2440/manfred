from __future__ import annotations

from typing import Any

from app.domain import FunctionToolDefinition, Tool, ToolExecutionContext
from app.services.filesystem import AgentFilesystemService, FilesystemSearchRequest, FilesystemSubject
from app.tools.definitions.filesystem.common import normalize_string_list, run_filesystem_action

SEARCH_FILE_PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Search root relative to workspace root '.agent_data'. "
                "Use '.' to search every available root, or paths like 'shared' and 'workspaces'."
            ),
        },
        "query": {"type": "string", "description": "Pattern to search for in filenames and/or file contents."},
        "patternMode": {"type": "string", "enum": ["literal", "regex", "fuzzy"]},
        "target": {"type": "string", "enum": ["all", "filename", "content"]},
        "caseInsensitive": {"type": "boolean"},
        "wholeWord": {"type": "boolean"},
        "multiline": {"type": "boolean"},
        "depth": {"type": "integer", "minimum": 0},
        "types": {"type": "array", "items": {"type": "string"}},
        "glob": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
        "exclude": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
        "maxResults": {"type": "integer", "minimum": 1},
        "respectIgnore": {"type": "boolean"},
    },
    "required": ["path", "query"],
    "additionalProperties": False,
}


def build_search_file_tool(filesystem_service: AgentFilesystemService) -> Tool:
    async def handle_search_file(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
        async def action(subject: FilesystemSubject, tool_name: str) -> dict[str, Any]:
            return await filesystem_service.search(
                FilesystemSearchRequest(
                    subject=subject,
                    tool_name=tool_name,
                    path=str(args.get("path", ".")),
                    query=str(args.get("query", "")),
                    pattern_mode=str(args.get("patternMode", "literal")),
                    target=str(args.get("target", "all")),
                    case_insensitive=bool(args.get("caseInsensitive", False)),
                    whole_word=bool(args.get("wholeWord", False)),
                    multiline=bool(args.get("multiline", False)),
                    depth=int(args.get("depth", 8)),
                    types=normalize_string_list(args.get("types")),
                    glob=args.get("glob"),
                    exclude=args.get("exclude"),
                    max_results=int(args.get("maxResults", 50)),
                    respect_ignore=bool(args.get("respectIgnore", True)),
                )
            )

        return await run_filesystem_action(context=context, action=action)

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="search_file",
            description=(
                "Search the workspace by filename and/or file content. Paths are relative to workspace root "
                "'.agent_data'; use '.' to search every available root."
            ),
            parameters=SEARCH_FILE_PARAMETERS,
        ),
        handler=handle_search_file,
    )
