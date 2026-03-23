from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib import error, parse, request

from app.agent.tools.files.common import WORKSPACE_ROOT, build_filesystem_tool, display_path, resolve_tool_path
from app.domain.tool import tool_error, tool_ok


async def download_file_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal

    url = args.get("url")
    if not isinstance(url, str) or url.strip() == "":
        return tool_error(
            "download_file expects a non-empty string argument: 'url'.",
            hint="Podaj pole 'url' jako pełny adres zaczynający się od 'http://' lub 'https://'.",
            details={
                "received": {"url": url},
                "expected": {"url": "absolute http/https URL"},
            },
        )

    normalized_url = url.strip()
    parsed_url = parse.urlparse(normalized_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        return tool_error(
            "download_file expects an absolute HTTP or HTTPS URL.",
            hint="Podaj pełny URL z protokołem 'http://' lub 'https://'.",
            details={
                "received": {"url": normalized_url},
                "expected": {"url": "absolute http/https URL"},
            },
        )

    req = request.Request(
        normalized_url,
        headers={
            "Accept": "*/*",
            "User-Agent": "manfred-download-file/1.0",
        },
        method="GET",
    )

    try:
        with request.urlopen(req, timeout=30.0) as response:
            content_bytes = response.read()
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            source_encoding = response.headers.get_content_charset()
    except error.HTTPError as exc:
        return tool_error(
            f"Could not download file: HTTP {exc.code}",
            hint="Sprawdź URL albo spróbuj ponownie później, jeśli źródło chwilowo nie odpowiada.",
            details={
                "url": normalized_url,
                "status_code": exc.code,
            },
        )
    except error.URLError as exc:
        return tool_error(
            f"Could not download file: {exc.reason}",
            hint="Sprawdź czy URL jest poprawny i dostępny z sieci.",
            details={
                "url": normalized_url,
                "reason": str(exc.reason),
            },
        )

    target_path = _resolve_output_path(normalized_url)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    is_text = _should_store_as_text(normalized_url, content_type)
    output: dict[str, Any] = {
        "path": display_path(target_path),
        "url": normalized_url,
        "content_type": content_type,
        "size": len(content_bytes),
        "is_text": is_text,
    }

    if is_text:
        text = content_bytes.decode(source_encoding or "utf-8", errors="replace")
        target_path.write_text(text, encoding="utf-8")
        output["encoding"] = "utf-8"
        output["preview"] = text[:1000]
    else:
        target_path.write_bytes(content_bytes)

    return tool_ok(output)


def _resolve_output_path(url: str) -> Path:
    parsed_url = parse.urlparse(url)
    filename = Path(parsed_url.path).name or "downloaded_file"
    return resolve_tool_path(str(Path("downloads") / filename))


def _should_store_as_text(url: str, content_type: str) -> bool:
    normalized_content_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    if normalized_content_type.startswith("text/"):
        return True

    if normalized_content_type in {
        "application/csv",
        "application/json",
        "application/xml",
        "text/csv",
        "text/xml",
    }:
        return True

    return Path(parse.urlparse(url).path).suffix.lower() in {
        ".csv",
        ".json",
        ".md",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }


download_file_tool = build_filesystem_tool(
    name="download_file",
    description=f"Download a file from an absolute HTTP or HTTPS URL and save it in downloads/ inside the workspace root ({WORKSPACE_ROOT}).",
    properties={
        "url": {
            "type": "string",
            "description": "Absolute HTTP or HTTPS URL of the file to download.",
        },
    },
    required=["url"],
    handler=download_file_handler,
)
