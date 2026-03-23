from __future__ import annotations

from difflib import unified_diff


def build_unified_diff(*, before: str, after: str, path: str) -> str:
    diff = unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    return "\n".join(diff)
