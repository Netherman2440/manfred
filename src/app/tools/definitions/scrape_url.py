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

        fmt = args.get("format", "markdown")
        if fmt not in ("markdown", "html"):
            return {"ok": False, "error": "'format' must be 'markdown' or 'html'"}

        only_main_content = args.get("only_main_content")
        if only_main_content is not None and not isinstance(only_main_content, bool):
            return {"ok": False, "error": "'only_main_content' must be a boolean"}

        wait_for = args.get("wait_for")
        if wait_for is not None and (not isinstance(wait_for, int) or isinstance(wait_for, bool) or wait_for < 0):
            return {"ok": False, "error": "'wait_for' must be a non-negative integer (milliseconds)"}

        raw_actions = args.get("actions")
        actions: list[dict[str, Any]] | None = None
        if raw_actions is not None:
            if not isinstance(raw_actions, list) or not all(
                isinstance(a, dict) and isinstance(a.get("type"), str) for a in raw_actions
            ):
                return {
                    "ok": False,
                    "error": "'actions' must be a list of objects, each with a string 'type' field",
                }
            actions = raw_actions

        if not context.workspace_path:
            return {
                "ok": False,
                "error": "scrape_url requires an active session workspace — no workspace_path on context",
            }

        formats = ["markdown", "html"] if fmt == "html" else ["markdown"]
        try:
            result = await scraper.scrape(
                url,
                actions=actions,
                formats=formats,
                only_main_content=only_main_content,
                wait_for=wait_for,
            )
        except WebScraperError as exc:
            return {"ok": False, "error": str(exc)}

        content = result.html if fmt == "html" else result.markdown
        if content is None:
            return {"ok": False, "error": f"Scraper returned no '{fmt}' content for {url}"}

        files_dir = Path(context.workspace_path) / SESSION_FILES_DIRNAME
        files_dir.mkdir(parents=True, exist_ok=True)
        target_path = files_dir / save_as
        target_path.write_text(content, encoding="utf-8")

        output: dict[str, Any] = {
            "url": result.final_url,
            "format": fmt,
            "bytes": len(content.encode("utf-8")),
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
                "Scrape a URL (renders JavaScript, handles Cloudflare) via Firecrawl, persist the result to "
                "workspace/files/<save_as>, and return only metadata (final url, bytes, path, optional HTTP "
                "status) — the body is NOT inlined to keep context small. Use read_file on the returned path. "
                "Supports authenticated/interactive pages via 'actions': a sequence of browser steps run before "
                "the final capture, in the same cloud browser, so a login session persists across the steps. "
                "Login pattern (fields filled one at a time): click the input by CSS selector, then write its "
                "value, repeat per field, then click submit, then wait, then capture. Example actions: "
                '[{"type":"click","selector":"input[name=login]"},{"type":"write","text":"Zofia"},'
                '{"type":"click","selector":"input[name=password]"},{"type":"write","text":"secret"},'
                '{"type":"click","selector":"button[type=submit]"},{"type":"wait","milliseconds":3000}]. '
                "Action types: click{selector}, write{text} (types into the focused element — always click the "
                "target input first), press{key}, wait{milliseconds|selector}, scroll{direction}, scrape, "
                "executeJavascript{script} (e.g. fetch an internal API inside the logged-in browser). "
                "To discover selectors or when expected content is missing, set format='html' and "
                "only_main_content=false to get the raw page HTML including <input> name/id attributes. "
                "For JavaScript- or Cloudflare-rendered pages, set wait_for (ms) so content renders before "
                "actions run and before capture. Use actions to log in and read only — never trigger controls "
                "that mutate data unless that is explicitly the task."
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
                    "format": {
                        "type": "string",
                        "enum": ["markdown", "html"],
                        "description": (
                            "Output format saved to the file. 'markdown' (default) = clean readable content. "
                            "'html' = raw HTML — use it to read form <input> selectors or when markdown drops "
                            "content you need."
                        ),
                    },
                    "only_main_content": {
                        "type": "boolean",
                        "description": (
                            "When true (default), Firecrawl strips boilerplate to main content. Set false to "
                            "keep the full page — needed to see login forms, nav, or data the main-content "
                            "heuristic would discard."
                        ),
                    },
                    "wait_for": {
                        "type": "integer",
                        "minimum": 0,
                        "description": (
                            "Milliseconds to wait for the page to render before running actions and "
                            "capturing. Set ~3000-5000 for JavaScript- or Cloudflare-gated pages; default 0."
                        ),
                    },
                    "actions": {
                        "type": "array",
                        "description": (
                            "Optional ordered browser steps run before capture (login, clicks, JS). Each item "
                            "is an object with a string 'type' and type-specific fields (see tool description)."
                        ),
                        "items": {"type": "object"},
                    },
                },
                "required": ["url", "save_as"],
                "additionalProperties": False,
            },
        ),
        handler=handle_scrape_url,
    )
