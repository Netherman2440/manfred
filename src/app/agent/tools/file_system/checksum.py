from __future__ import annotations

from hashlib import sha256


def short_checksum(content: str | bytes) -> str:
    data = content.encode("utf-8") if isinstance(content, str) else content
    return sha256(data).hexdigest()[:12]
