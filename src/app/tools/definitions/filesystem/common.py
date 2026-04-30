from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.domain import ToolExecutionContext
from app.services.filesystem import FilesystemSubject, FilesystemToolError


FilesystemAction = Callable[[FilesystemSubject, str], Awaitable[dict[str, Any]]]


def build_filesystem_subject(context: ToolExecutionContext) -> FilesystemSubject:
    return FilesystemSubject(
        user_id=context.user_id,
        session_id=context.session_id,
        agent_id=context.agent_id,
        user_name=context.user_name,
    )


def normalize_string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


async def run_filesystem_action(
    *,
    context: ToolExecutionContext,
    action: FilesystemAction,
) -> dict[str, bool | str]:
    subject = build_filesystem_subject(context)
    try:
        payload = await action(subject, context.tool_name)
    except FilesystemToolError as exc:
        return {"ok": False, "error": exc.as_text()}
    except ValueError as exc:
        message = str(exc)
        if "path" in message.lower() or "absolute paths" in message.lower() or ".." in message:
            hint = (
                "Use workspace-relative paths such as 'agents/example.agent.md' or "
                "'shared/docs/note.md'. Do not start paths with '/' and do not use host filesystem paths."
            )
            return {"ok": False, "error": f"{message} Hint: {hint}"}
        return {"ok": False, "error": message}

    return {"ok": True, "output": json.dumps(payload, ensure_ascii=True)}
