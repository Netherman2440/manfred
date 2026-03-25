from __future__ import annotations

import re
from difflib import SequenceMatcher
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from app.agent.tools.file_system.common import (
    WORKSPACE_ROOT,
    build_filesystem_tool,
    display_path,
    invalid_argument_error,
    validate_bool_argument,
    validate_int_argument,
    validate_string_argument,
    validate_string_list_argument,
)
from app.agent.tools.file_system.path_guard import path_kind, resolve_workspace_path
from app.agent.tools.file_system.text_utils import is_text_file, read_utf8_text
from app.domain.tool import tool_ok


FS_SEARCH_PROPERTIES = {
    "path": {
        "type": "string",
        "description": "Relative search root inside the workspace.",
        "default": ".",
    },
    "pattern": {
        "type": "string",
        "description": "Search pattern for filenames or file content.",
    },
    "target": {
        "type": "string",
        "enum": ["filename", "content", "all"],
        "default": "all",
    },
    "pattern_mode": {
        "type": "string",
        "enum": ["literal", "regex", "fuzzy"],
        "default": "literal",
    },
    "case_insensitive": {
        "type": "boolean",
        "default": True,
    },
    "whole_word": {
        "type": "boolean",
        "default": False,
    },
    "multiline": {
        "type": "boolean",
        "default": False,
    },
    "depth": {
        "type": "integer",
        "default": 8,
    },
    "max_results": {
        "type": "integer",
        "default": 50,
    },
    "glob": {
        "type": "array",
        "items": {"type": "string"},
    },
    "exclude": {
        "type": "array",
        "items": {"type": "string"},
    },
}


def _iter_files(root: Path, *, max_depth: int) -> list[Path]:
    collected: list[Path] = []

    def visit(current: Path, depth: int) -> None:
        if depth > max_depth:
            return

        children = sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower(), item.name))
        for child in children:
            if child.is_dir():
                visit(child, depth + 1)
                continue
            collected.append(child)

    visit(root, 0)
    return sorted(collected, key=lambda path: path.relative_to(root).as_posix())


def _allowed(path: Path, root: Path, *, include: list[str], exclude: list[str]) -> bool:
    relative_path = path.relative_to(root).as_posix()
    if include and not any(fnmatch(relative_path, pattern) for pattern in include):
        return False
    if exclude and any(fnmatch(relative_path, pattern) for pattern in exclude):
        return False
    return True


def _build_regex(pattern: str, *, case_insensitive: bool, whole_word: bool, multiline: bool) -> re.Pattern[str]:
    if len(pattern) > 200:
        raise ValueError("Regex pattern is too long.")
    if re.search(r"\([^)]*[+*][^)]*\)[+*{]", pattern):
        raise ValueError("Regex pattern looks unsafe for this tool.")

    expression = pattern
    if whole_word:
        expression = rf"\b(?:{expression})\b"

    flags = 0
    if case_insensitive:
        flags |= re.IGNORECASE
    if multiline:
        flags |= re.MULTILINE
    return re.compile(expression, flags)


def _literal_matches(value: str, pattern: str, *, case_insensitive: bool, whole_word: bool) -> bool:
    haystack = value.lower() if case_insensitive else value
    needle = pattern.lower() if case_insensitive else pattern
    if not whole_word:
        return needle in haystack
    return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None


def _fuzzy_score(value: str, pattern: str, *, case_insensitive: bool) -> float:
    left = value.lower() if case_insensitive else value
    right = pattern.lower() if case_insensitive else pattern
    return SequenceMatcher(a=left, b=right).ratio()


async def fs_search_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
    del signal
    raw_path = args.get("path", ".")
    if isinstance(raw_path, str) and raw_path.strip() == "":
        path = "."
    else:
        path = validate_string_argument(args, "path", tool_name="fs_search", default=".")
        if isinstance(path, dict):
            return path
    pattern = validate_string_argument(args, "pattern", tool_name="fs_search")
    if isinstance(pattern, dict):
        return pattern
    target = validate_string_argument(args, "target", tool_name="fs_search", default="all")
    if isinstance(target, dict):
        return target
    pattern_mode = validate_string_argument(args, "pattern_mode", tool_name="fs_search", default="literal")
    if isinstance(pattern_mode, dict):
        return pattern_mode
    case_insensitive = validate_bool_argument(args, "case_insensitive", tool_name="fs_search", default=True)
    if isinstance(case_insensitive, dict):
        return case_insensitive
    whole_word = validate_bool_argument(args, "whole_word", tool_name="fs_search", default=False)
    if isinstance(whole_word, dict):
        return whole_word
    multiline = validate_bool_argument(args, "multiline", tool_name="fs_search", default=False)
    if isinstance(multiline, dict):
        return multiline
    depth = validate_int_argument(args, "depth", tool_name="fs_search", default=8, min_value=0)
    if isinstance(depth, dict):
        return depth
    max_results = validate_int_argument(args, "max_results", tool_name="fs_search", default=50, min_value=1)
    if isinstance(max_results, dict):
        return max_results
    include = validate_string_list_argument(args, "glob", tool_name="fs_search")
    if isinstance(include, dict):
        return include
    exclude = validate_string_list_argument(args, "exclude", tool_name="fs_search")
    if isinstance(exclude, dict):
        return exclude

    if target not in {"filename", "content", "all"}:
        return invalid_argument_error("fs_search", "target", expected="'filename', 'content' or 'all'", received=target)
    if pattern_mode not in {"literal", "regex", "fuzzy"}:
        return invalid_argument_error(
            "fs_search",
            "pattern_mode",
            expected="'literal', 'regex' or 'fuzzy'",
            received=pattern_mode,
        )

    resolved = resolve_workspace_path(path, tool_name="fs_search")
    if isinstance(resolved, dict):
        return resolved
    if path_kind(resolved) != "directory":
        return invalid_argument_error("fs_search", "path", expected="existing directory", received=path)

    regex: re.Pattern[str] | None = None
    if pattern_mode == "regex":
        try:
            regex = _build_regex(
                pattern,
                case_insensitive=case_insensitive,
                whole_word=whole_word,
                multiline=multiline,
            )
        except ValueError as exc:
            return invalid_argument_error("fs_search", "pattern", expected=str(exc), received=pattern)

    results: list[dict[str, Any]] = []

    for file_path in _iter_files(resolved, max_depth=depth):
        if not _allowed(file_path, resolved, include=include, exclude=exclude):
            continue

        relative_path = file_path.relative_to(resolved).as_posix()
        workspace_path = display_path(file_path)

        if target in {"filename", "all"}:
            filename = file_path.name
            matched = False
            score = None
            if pattern_mode == "literal":
                matched = _literal_matches(filename, pattern, case_insensitive=case_insensitive, whole_word=whole_word)
            elif pattern_mode == "regex":
                assert regex is not None
                matched = regex.search(filename) is not None
            else:
                score = _fuzzy_score(filename, pattern, case_insensitive=case_insensitive)
                matched = score >= 0.6

            if matched:
                payload = {
                    "path": workspace_path,
                    "target": "filename",
                    "match": filename,
                }
                if score is not None:
                    payload["score"] = round(score, 3)
                results.append(payload)
                if len(results) >= max_results:
                    break

        if len(results) >= max_results or target == "filename":
            continue

        if not is_text_file(file_path):
            continue

        content = read_utf8_text(file_path)
        lines = content.splitlines()
        if pattern_mode == "literal":
            for line_number, line in enumerate(lines, start=1):
                if _literal_matches(line, pattern, case_insensitive=case_insensitive, whole_word=whole_word):
                    results.append(
                        {
                            "path": workspace_path,
                            "target": "content",
                            "line": line_number,
                            "text": line,
                        }
                    )
                    if len(results) >= max_results:
                        break
        elif pattern_mode == "regex":
            assert regex is not None
            if multiline:
                for match in regex.finditer(content):
                    line_number = content.count("\n", 0, match.start()) + 1
                    line = lines[line_number - 1] if line_number - 1 < len(lines) else ""
                    results.append(
                        {
                            "path": workspace_path,
                            "target": "content",
                            "line": line_number,
                            "text": line,
                        }
                    )
                    if len(results) >= max_results:
                        break
            else:
                for line_number, line in enumerate(lines, start=1):
                    if regex.search(line):
                        results.append(
                            {
                                "path": workspace_path,
                                "target": "content",
                                "line": line_number,
                                "text": line,
                            }
                        )
                        if len(results) >= max_results:
                            break
        else:
            for line_number, line in enumerate(lines, start=1):
                score = _fuzzy_score(line, pattern, case_insensitive=case_insensitive)
                if score >= 0.6:
                    results.append(
                        {
                            "path": workspace_path,
                            "target": "content",
                            "line": line_number,
                            "text": line,
                            "score": round(score, 3),
                        }
                    )
                    if len(results) >= max_results:
                        break

        if len(results) >= max_results:
            break

    return tool_ok(
        {
            "success": True,
            "path": display_path(resolved),
            "pattern": pattern,
            "target": target,
            "pattern_mode": pattern_mode,
            "count": len(results),
            "results": results,
            "workspace_root": str(WORKSPACE_ROOT),
        }
    )


fs_search_tool = build_filesystem_tool(
    name="fs_search",
    description=f"Search filenames and UTF-8 text content inside the workspace root ({WORKSPACE_ROOT}).",
    properties=FS_SEARCH_PROPERTIES,
    required=["pattern"],
    handler=fs_search_handler,
)
