from __future__ import annotations

from pathlib import Path


def is_text_file(path: Path) -> bool:
    try:
        sample = path.read_bytes()[:8192]
    except OSError:
        return False

    if b"\x00" in sample:
        return False

    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def read_utf8_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")
