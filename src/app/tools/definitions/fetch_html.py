from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
from markdownify import markdownify

from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext

REQUEST_TIMEOUT = 30.0
FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
SESSION_FILES_DIRNAME = "files"
USER_AGENT = "Mozilla/5.0 (compatible; ManfredFetchHtml/1.0)"
STRIP_TAGS_PATTERN = re.compile(
    r"<(script|style|noscript)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)


async def handle_fetch_html(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
    raw_url = args.get("url")
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise ValueError("'url' must be a non-empty string")
    url = raw_url.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("'url' must be an absolute http(s) URL")

    raw_save_as = args.get("save_as")
    if not isinstance(raw_save_as, str) or not raw_save_as.strip():
        raise ValueError("'save_as' must be a non-empty string")
    save_as = raw_save_as.strip()
    if not FILENAME_PATTERN.match(save_as):
        raise ValueError(
            "'save_as' must be a single path segment (letters, digits, dot, underscore, hyphen — no slashes)"
        )

    fmt = args.get("format", "markdown")
    if fmt not in ("markdown", "html"):
        raise ValueError("'format' must be 'markdown' or 'html'")

    if not context.workspace_path:
        raise ValueError("fetch_html requires an active session workspace — no workspace_path on context")

    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            return {"ok": False, "error": f"HTTP error fetching {url}: {exc}"}

    if response.status_code >= 400:
        return {"ok": False, "error": f"HTTP {response.status_code} from {url}"}

    raw_html = response.text
    cleaned = STRIP_TAGS_PATTERN.sub("", raw_html)

    if fmt == "markdown":
        body = markdownify(cleaned, heading_style="ATX").strip()
    else:
        body = cleaned

    files_dir = Path(context.workspace_path) / SESSION_FILES_DIRNAME
    files_dir.mkdir(parents=True, exist_ok=True)
    target_path = files_dir / save_as
    target_path.write_text(body, encoding="utf-8")

    output = {
        "status": response.status_code,
        "url": str(response.url),
        "format": fmt,
        "bytes": len(body.encode("utf-8")),
        "path": f"workspace/{SESSION_FILES_DIRNAME}/{save_as}",
        "hint": "Use read_file with the returned path to inspect contents.",
    }
    return {"ok": True, "output": json.dumps(output, ensure_ascii=False)}


fetch_html_tool = Tool(
    type="sync",
    definition=FunctionToolDefinition(
        name="fetch_html",
        description=(
            "Fetch an arbitrary public HTML page, strip <script>/<style>/<noscript>, "
            "convert to markdown by default (set format='html' to keep raw HTML), and "
            "persist to the current session workspace at workspace/files/<save_as>. "
            "Returns only metadata (status, final url after redirects, format, bytes, "
            "workspace-relative path) — the body is NOT inlined to keep the context small. "
            "Use read_file on the returned path to read the contents."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Absolute http(s) URL of the HTML page to fetch.",
                },
                "save_as": {
                    "type": "string",
                    "description": (
                        "Filename to save under workspace/files/, e.g. 'drone.md'. "
                        "Single path segment only — no slashes, no leading directories."
                    ),
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "html"],
                    "description": "Output format. Defaults to 'markdown'.",
                },
            },
            "required": ["url", "save_as"],
            "additionalProperties": False,
        },
    ),
    handler=handle_fetch_html,
)
