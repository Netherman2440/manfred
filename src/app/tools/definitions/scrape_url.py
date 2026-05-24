from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext
from app.services.web_scraper import BaseWebScraperService, WebScraperError

FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
SESSION_FILES_DIRNAME = "files"


def build_scrape_url_tool(scraper: BaseWebScraperService) -> Tool:
    async def handle_scrape_url(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
        raw_url = args.get("url")
        if not isinstance(raw_url, str) or not raw_url.strip():
            return {"ok": False, "error": "'url' must be a non-empty string"}
        url = raw_url.strip()
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "'url' must be an absolute http(s) URL"}

        raw_save_as = args.get("save_as")
        if not isinstance(raw_save_as, str) or not raw_save_as.strip():
            return {"ok": False, "error": "'save_as' must be a non-empty string"}
        save_as = raw_save_as.strip()
        if not FILENAME_PATTERN.match(save_as):
            return {
                "ok": False,
                "error": (
                    "'save_as' must be a single path segment (letters, digits, dot, underscore, hyphen — no slashes)"
                ),
            }

        if not context.workspace_path:
            return {
                "ok": False,
                "error": "scrape_url requires an active session workspace — no workspace_path on context",
            }

        try:
            result = await scraper.scrape(url)
        except WebScraperError as exc:
            return {"ok": False, "error": str(exc)}

        files_dir = Path(context.workspace_path) / SESSION_FILES_DIRNAME
        files_dir.mkdir(parents=True, exist_ok=True)
        target_path = files_dir / save_as
        target_path.write_text(result.markdown, encoding="utf-8")

        output: dict[str, Any] = {
            "url": result.final_url,
            "format": "markdown",
            "bytes": result.byte_count,
            "path": f"workspace/{SESSION_FILES_DIRNAME}/{save_as}",
            "hint": "Use read_file with the returned path to inspect contents.",
        }
        if result.status_code is not None:
            output["status"] = result.status_code

        return {"ok": True, "output": json.dumps(output, ensure_ascii=False)}

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="scrape_url",
            description=(
                "Scrape an arbitrary public URL (renders JavaScript) via Firecrawl, return clean main-content "
                "markdown, and persist it to the current session workspace at workspace/files/<save_as>. "
                "Returns only metadata (final url after redirects, bytes, workspace-relative path, optional "
                "HTTP status) — the body is NOT inlined to keep context small. Use read_file on the returned "
                "path to read the contents."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Absolute http(s) URL of the page to scrape.",
                    },
                    "save_as": {
                        "type": "string",
                        "description": (
                            "Filename to save under workspace/files/, e.g. 'reactor.md'. "
                            "Single path segment only — no slashes, no leading directories."
                        ),
                    },
                },
                "required": ["url", "save_as"],
                "additionalProperties": False,
            },
        ),
        handler=handle_scrape_url,
    )
