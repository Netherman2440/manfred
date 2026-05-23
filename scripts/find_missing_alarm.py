"""Szukaj 1 brakującego alarm-sensora — skanuj OK-klasyfikowane notatki pod kątem nowych alarm-fraz."""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.services.sensors import SensorService  # noqa: E402

ALARM_HOTWORDS = [
    "troubleshooting", "doubtful", "should be investigated", "investigation is completed",
    "under investigation", "suspicious", "quality audit", "unreliable", "urgent verification",
    "unusual", "escalated", "maintenance follow-up", "root-cause analysis", "flagged it",
    "quality control", "probable fault", "potential fault", "diagnostic task",
    "engineering analysis", "degradation", "signs of malfunction", "signs of an issue",
    "instability", "unstable", "irregularity", "inconsistency", "inconsistent",
    "compromised", "anomaly check", "visible anomaly", "behavior is concerning",
    "raises serious doubts", "not trustworthy", "not comfortable", "did not look right",
    "does not match healthy", "does not look healthy", "not the pattern i expected",
    "outside expected behavior", "conflicts with our baseline", "safety-minded review",
    "consistency is clearly broken", "cannot be treated as normal", "requires attention",
    "questionable behavior", "replacement assessment", "revalidation", "on-site inspection",
    "technicians to inspect", "unexpected pattern", "confidence in this report is low",
    "changed in a risky way", "stream contains signs", "operating picture is not trustworthy",
    "pattern indicates probable",
]

# Suspicious words to search in "OK" notes — words that suggest something is off
SUSPICION_INDICATORS = [
    "fault", "fail", "error", "warning", "alert", "alarm", "broken", "wrong",
    "issue", "problem", "defect", "abnormal", "strange", "weird", "off",
    "drift", "deviation", "irregular", "concern", "doubt", "verify", "check",
    "inspect", "audit", "review", "investigate", "anomal", "instab",
    "replace", "service", "maintenance", "diagnos", "engineer", "technician",
    "flag", "escalat", "report", "fault", "outlier", "spike", "jump",
    "unexpected", "unusual", "unstable", "unhealthy", "questionable",
    "not normal", "not healthy", "not right", "not safe", "not acceptable",
    "not approve", "do not", "does not", "did not", "cannot", "compromised",
    "risky", "risk", "danger", "critical", "severe",
]


def has_alarm_hotword(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in ALARM_HOTWORDS)


def main() -> None:
    sensors_dir = ROOT / ".agent_data/default-user/shared/aidevs/data/sensors"
    service = SensorService(sensors_dir=sensors_dir)
    sensors = service.get_sensors()

    # Collect notes classified as OK by my hotword filter
    ok_notes_with_ids: dict[str, list[str]] = {}
    for s in sensors:
        note = s.operator_notes.strip()
        if not note:
            continue
        if not has_alarm_hotword(note):
            ok_notes_with_ids.setdefault(note, []).append(s.file_id)

    # Count distinct OK notes
    print(f"Distinct OK notes: {len(ok_notes_with_ids)}")

    # Search for suspicion indicators in OK notes
    print(f"\n=== OK-notes containing suspicion indicators ===")
    flagged: list[tuple[str, str, list[str]]] = []
    for note, ids in ok_notes_with_ids.items():
        nl = note.lower()
        hits = [w for w in SUSPICION_INDICATORS if w in nl]
        if hits:
            flagged.append((note, ", ".join(hits), ids))

    # Filter out OK negation patterns (text contains "no X" or "nothing suggests" etc)
    NEGATION_PATTERNS = [
        r"\bno concerning drift\b", r"\bnothing suggests\b", r"\bno irregular behavior\b",
        r"\bno warning signs\b", r"\bno sign of abnormal\b", r"\bno deviations\b",
        r"\bnormal operation continues without\b", r"\bwithout drift\b",
        r"\bno intervention\b", r"\bno escalation\b", r"\bno corrective\b",
        r"\bnothing to flag\b", r"\bno anomal\b", r"\bno fault\b",
    ]

    def is_pure_negated(text: str) -> bool:
        t = text.lower()
        for pat in NEGATION_PATTERNS:
            if re.search(pat, t):
                return True
        return False

    flagged.sort(key=lambda x: (len(x[2]), x[0]))  # rarest first
    print("\n=== Low-frequency suspicion-flagged OK notes (count <= 3, no obvious negation) ===")
    for note, hits, ids in flagged:
        if len(ids) > 3:
            continue
        if is_pure_negated(note):
            continue
        print(f"\nHITS: {hits}  COUNT: {len(ids)}  IDs: {ids}")
        print(f"NOTE: {note}")

    print(f"\n\nTotal OK-notes with suspicion indicators: {len(flagged)}")

    # Show clause-frequency distribution of OK notes — most common clauses
    print("\n=== Top 30 most-frequent OK clauses ===")
    clause_counter: Counter[str] = Counter()
    for note, ids in ok_notes_with_ids.items():
        for clause in [c.strip() for c in note.split(",")]:
            if clause:
                clause_counter[clause] += len(ids)
    for clause, count in clause_counter.most_common(30):
        print(f"{count:5d}  {clause}")


if __name__ == "__main__":
    main()
