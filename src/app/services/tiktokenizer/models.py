from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenCount:
    model: str
    encoding: str
    tokens: int
    chars: int
