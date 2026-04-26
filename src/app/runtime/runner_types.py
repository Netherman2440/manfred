from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain import Agent


RunStatus = Literal["completed", "waiting", "failed", "cancelled"]


@dataclass(slots=True, frozen=True)
class RunResult:
    ok: bool
    status: RunStatus
    agent: Agent | None = None
    error: str | None = None
