"""Skanuj wszystkie sensory, znajdź te z alarmującą operator_notes."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.services.sensors import SensorService  # noqa: E402

ALARM_HOTWORDS = [
    "troubleshooting",
    "doubtful",
    "should be investigated",
    "investigation is completed",
    "under investigation",
    "suspicious",
    "quality audit",
    "unreliable",
    "urgent verification",
    "unusual",
    "escalated",
    "maintenance follow-up",
    "root-cause analysis",
    "flagged it",
    "quality control",
    "probable fault",
    "potential fault",
    "diagnostic task",
    "engineering analysis",
    "degradation",
    "signs of malfunction",
    "signs of an issue",
    "instability",
    "unstable",
    "irregularity",
    "inconsistency",
    "inconsistent",
    "compromised",
    "anomaly check",
    "visible anomaly",
    "behavior is concerning",
    "raises serious doubts",
    "not trustworthy",
    "not comfortable",
    "did not look right",
    "does not match healthy",
    "does not look healthy",
    "not the pattern i expected",
    "outside expected behavior",
    "conflicts with our baseline",
    "safety-minded review",
    "consistency is clearly broken",
    "cannot be treated as normal",
    "requires attention",
    "questionable behavior",
    "replacement assessment",
    "revalidation",
    "on-site inspection",
    "technicians to inspect",
    "unexpected pattern",
    "confidence in this report is low",
    "changed in a risky way",
    "stream contains signs",
    "operating picture is not trustworthy",
    "pattern indicates probable",
]


def has_alarm(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in ALARM_HOTWORDS)

CLEANED = {
    "1053", "2044", "2238", "3713", "4040",
    "1819", "4237", "8457",
    "1269", "2500", "4888", "5022",
    "0567", "0753", "2175", "5156", "8168", "8410", "9151", "9604",
    "0307", "6281",
    "5405", "5799", "8076", "9288", "9848", "0158", "1678", "2958", "3123",
    "4630", "7680", "7701", "9583", "0516", "4186", "4673", "5714", "5715",
    "6197", "6336", "1632", "3798", "9422", "9518",
    "5000", "9614", "1743", "8369", "7266",
}


def main() -> None:
    sensors_dir = ROOT / ".agent_data/default-user/shared/aidevs/data/sensors"
    service = SensorService(sensors_dir=sensors_dir)
    sensors = service.get_sensors()
    print(f"Loaded {len(sensors)} sensors from {sensors_dir}")

    alarm_ids: list[str] = []
    distinct_alarm_notes: set[str] = set()
    distinct_ok_notes: set[str] = set()
    distinct_alarm_clauses: set[str] = set()

    for s in sensors:
        note = s.operator_notes.strip()
        if not note:
            continue
        if has_alarm(note):
            alarm_ids.append(s.file_id)
            distinct_alarm_notes.add(note)
            for clause in [c.strip() for c in note.split(",")]:
                if clause and has_alarm(clause):
                    distinct_alarm_clauses.add(clause)
        else:
            distinct_ok_notes.add(note)

    alarm_set = set(alarm_ids)
    print(f"\nAlarm sensors (by operator_notes): {len(alarm_set)}")
    print(f"Distinct alarm notes (full): {len(distinct_alarm_notes)}")
    print(f"Distinct alarm clauses: {len(distinct_alarm_clauses)}")
    print(f"Distinct OK notes: {len(distinct_ok_notes)}")

    missing_from_cleaned = sorted(alarm_set - CLEANED)
    extra_in_cleaned = sorted(CLEANED - alarm_set)

    print(f"\nIN alarm_set but NOT in cleaned: {len(missing_from_cleaned)}")
    for sid in missing_from_cleaned:
        sensor = next(s for s in sensors if s.file_id == sid)
        print(f"  {sid} types={sensor.sensor_types} notes={sensor.operator_notes!r}")

    print(f"\nIN cleaned but NOT alarm_set: {len(extra_in_cleaned)}")
    for sid in extra_in_cleaned:
        sensor = next(s for s in sensors if s.file_id == sid)
        print(f"  {sid} types={sensor.sensor_types} notes={sensor.operator_notes!r}")

    out = ROOT / ".agent_data/default-user/shared/aidevs/tasks/evaluation/extracted_alarm.md"
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# Alarm sensors extracted programatically\n\n")
        f.write(f"Total sensors scanned: {len(sensors)}\n")
        f.write(f"Alarm sensors: {len(alarm_set)}\n")
        f.write(f"Distinct alarm notes (full): {len(distinct_alarm_notes)}\n")
        f.write(f"Distinct alarm clauses: {len(distinct_alarm_clauses)}\n")
        f.write(f"Distinct OK notes: {len(distinct_ok_notes)}\n\n")

        f.write("## In alarm_set but NOT in cleaned (NEW)\n\n")
        for sid in missing_from_cleaned:
            sensor = next(s for s in sensors if s.file_id == sid)
            f.write(f"- **{sid}** types={list(sensor.sensor_types)} `{sensor.operator_notes}`\n")
        f.write("\n## In cleaned but NOT in alarm_set\n\n")
        for sid in extra_in_cleaned:
            sensor = next(s for s in sensors if s.file_id == sid)
            f.write(f"- **{sid}** types={list(sensor.sensor_types)} `{sensor.operator_notes}`\n")

        f.write("\n## All distinct alarm clauses\n\n")
        for c in sorted(distinct_alarm_clauses):
            f.write(f"- {c}\n")
        f.write("\n## All distinct OK notes\n\n")
        for c in sorted(distinct_ok_notes):
            f.write(f"- {c}\n")

    print(f"\nWrote: {out}")


if __name__ == "__main__":
    main()
