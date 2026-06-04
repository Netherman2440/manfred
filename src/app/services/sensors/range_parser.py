from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RangeSegment:
    lo: float | None
    hi: float | None

    def matches(self, value: float) -> bool:
        if self.lo is not None and value < self.lo:
            return False
        if self.hi is not None and value > self.hi:
            return False
        return True


def parse_range(spec: str) -> list[RangeSegment]:
    text = spec.strip()
    if not text:
        raise ValueError("Empty range spec")

    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        raise ValueError("Empty range spec")

    segments: list[RangeSegment] = []
    for part in parts:
        if "-" in part:
            lo_str, hi_str = part.split("-", 1)
            lo_str, hi_str = lo_str.strip(), hi_str.strip()
            if not lo_str and not hi_str:
                raise ValueError(f"Invalid range segment: {part!r}")
            lo = float(lo_str) if lo_str else None
            hi = float(hi_str) if hi_str else None
            if lo is not None and hi is not None and lo > hi:
                raise ValueError(f"Invalid range segment (lo > hi): {part!r}")
            segments.append(RangeSegment(lo=lo, hi=hi))
        else:
            try:
                value = float(part)
            except ValueError as exc:
                raise ValueError(f"Invalid range segment: {part!r}") from exc
            segments.append(RangeSegment(lo=value, hi=value))

    return segments


def matches_range(value: float, spec: str | None) -> bool:
    if spec is None:
        return True
    segments = parse_range(spec)
    return any(segment.matches(value) for segment in segments)
