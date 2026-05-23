from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext

DEFAULT_PROMPT = "Describe this image in detail."
REQUEST_TIMEOUT = 60.0
_URL_SCHEMES = ("http://", "https://")


def _is_url(value: str) -> bool:
    return value.startswith(_URL_SCHEMES)


def _resolve_local_path(workspace_path: str, raw_path: str) -> Path:
    cleaned = raw_path.strip().lstrip("/")
    if cleaned.startswith("workspace/"):
        cleaned = cleaned[len("workspace/") :]
    if not cleaned:
        raise ValueError("'path' resolves to an empty local path")

    relative = Path(cleaned)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("'path' must be a workspace-relative path with no '..'")

    workspace_root = Path(workspace_path).resolve()
    candidate = (workspace_root / relative).resolve()
    if workspace_root != candidate and workspace_root not in candidate.parents:
        raise ValueError("'path' must resolve inside the session workspace")
    if not candidate.is_file():
        raise ValueError(f"local image not found at '{raw_path}'")
    return candidate


def _to_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if mime is None or not mime.startswith("image/"):
        raise ValueError(f"file does not look like an image (mime={mime}): {path.name}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def build_interprete_image_tool(settings: Settings) -> Tool:
    async def handle_interprete_image(
        args: dict[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, bool | str]:
        raw_path = args.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("'path' must be a non-empty string (URL or workspace-relative path)")
        path_arg = raw_path.strip()

        raw_prompt = args.get("prompt")
        if raw_prompt is None:
            prompt = DEFAULT_PROMPT
        elif isinstance(raw_prompt, str) and raw_prompt.strip():
            prompt = raw_prompt.strip()
        else:
            raise ValueError("'prompt' must be a non-empty string when provided")

        if _is_url(path_arg):
            image_url = path_arg
            source = "url"
        else:
            if not context.workspace_path:
                raise ValueError("interprete_image requires an active session workspace to resolve local paths")
            local = _resolve_local_path(context.workspace_path, path_arg)
            image_url = _to_data_url(local)
            source = "local"

        api_key = settings.OPEN_ROUTER_API_KEY.strip()
        if not api_key:
            raise ValueError("OPEN_ROUTER_API_KEY is not configured — set it in .env")

        payload = {
            "model": settings.OPEN_ROUTER_VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
        }
        url = f"{settings.OPEN_ROUTER_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                return {"ok": False, "error": f"HTTP error calling vision model: {exc}"}

        if response.status_code != 200:
            detail = response.text[:500]
            return {
                "ok": False,
                "error": f"vision request failed status {response.status_code}: {detail}",
            }

        try:
            data = response.json()
        except ValueError:
            return {"ok": False, "error": "vision response was not valid JSON"}

        choices = data.get("choices") or []
        if not choices:
            return {"ok": False, "error": "vision response had no choices"}
        message = choices[0].get("message") or {}
        description = _extract_text(message.get("content"))
        usage = data.get("usage") or {}

        output = {
            "description": description,
            "model": data.get("model") or settings.OPEN_ROUTER_VISION_MODEL,
            "source": source,
            "prompt": prompt,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
        }
        return {"ok": True, "output": json.dumps(output, ensure_ascii=False)}

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="interprete_image",
            description=(
                "Interpret an image with a vision-capable LLM and return a textual description. "
                "Accepts either a public HTTP(S) URL or a workspace-relative path "
                "(e.g. 'workspace/files/drone.png' or 'files/drone.png') — local files are "
                "read and base64-encoded into a data URL before being sent to the model. "
                "Optional 'prompt' overrides the default question with a custom instruction "
                "(e.g. 'Czy na zdjęciu znajduje się kotek?')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "HTTP(S) URL of the image OR a workspace-relative path such as "
                            "'workspace/files/drone.png'. Local paths must stay inside the "
                            "session workspace — no '..', no absolute paths."
                        ),
                    },
                    "prompt": {
                        "type": "string",
                        "description": (
                            "Optional instruction for the vision model. Use it to ask a "
                            "specific question about the image (e.g. 'Is there a cat?'). "
                            f"Defaults to: '{DEFAULT_PROMPT}'."
                        ),
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        handler=handle_interprete_image,
    )
