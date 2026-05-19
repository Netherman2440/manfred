from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ObservationResult:
    observations: str
    current_task: str | None


@dataclass(slots=True, frozen=True)
class ObserveOutcome:
    result: ObservationResult | None
    status: str  # "success" | "locked" | "below_threshold" | "no_unobserved" | "error"
    detail: str | None = None
