import json
from pathlib import Path

import pytest

from app.services.sensors import SensorService


def _write_sensor(directory: Path, file_id: str, **overrides) -> None:
    payload = {
        "sensor_type": "temperature/voltage",
        "timestamp": 1774064280,
        "temperature_K": 0.0,
        "pressure_bar": 0.0,
        "water_level_meters": 0.0,
        "voltage_supply_v": 0.0,
        "humidity_percent": 0.0,
        "operator_notes": "",
    }
    payload.update(overrides)
    (directory / f"{file_id}.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def sensors_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "sensors"
    directory.mkdir()
    _write_sensor(
        directory,
        "0001",
        sensor_type="temperature/voltage",
        temperature_K=300.0,
        voltage_supply_v=230.4,
        humidity_percent=40.0,
        operator_notes="Readings look stable and within expected range.",
    )
    _write_sensor(
        directory,
        "0002",
        sensor_type="voltage/water",
        temperature_K=0.0,
        water_level_meters=13.4,
        voltage_supply_v=229.0,
        operator_notes="Calm and predictable signal.",
    )
    _write_sensor(
        directory,
        "0003",
        sensor_type="pressure",
        pressure_bar=5.5,
        humidity_percent=90.0,
        operator_notes="Pressure spike detected.",
    )
    _write_sensor(
        directory,
        "0004",
        sensor_type="temperature/voltage",
        temperature_K=612.0,
        voltage_supply_v=240.0,
        humidity_percent=10.0,
        operator_notes="Hot day, readings high.",
    )
    return directory


def test_load_sensors_reads_all_files(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    service.load_sensors()
    all_sensors = service.get_sensors()
    assert len(all_sensors) == 4
    assert [s.file_id for s in all_sensors] == ["0001", "0002", "0003", "0004"]


def test_sensor_types_parsed_as_tuple(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    by_id = {s.file_id: s for s in service.get_sensors()}
    assert by_id["0001"].sensor_types == ("temperature", "voltage")
    assert by_id["0002"].sensor_types == ("voltage", "water")
    assert by_id["0003"].sensor_types == ("pressure",)


def test_get_sensors_loads_lazily(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors()
    assert len(result) == 4


def test_load_sensors_idempotent(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    service.load_sensors()
    first_ids = [s.file_id for s in service.get_sensors()]
    _write_sensor(sensors_dir, "9999", sensor_type="extra")
    service.load_sensors()
    second_ids = [s.file_id for s in service.get_sensors()]
    assert first_ids == second_ids


def test_filter_by_sensor_type_substring(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(sensor_type="voltage")
    assert {s.file_id for s in result} == {"0001", "0002", "0004"}


def test_filter_by_temp_range_open_upper(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(temp_range="500-")
    assert {s.file_id for s in result} == {"0004"}


def test_filter_by_temp_range_open_lower(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(temp_range="-100")
    assert {s.file_id for s in result} == {"0002", "0003"}


def test_filter_by_disjoint_ranges(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(humidity_range="-15, 80-")
    assert {s.file_id for s in result} == {"0002", "0003", "0004"}


def test_filter_by_notes_contains_case_insensitive(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(notes_contains="STABLE")
    assert {s.file_id for s in result} == {"0001"}


def test_filter_by_notes_contains_list_any_match(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(notes_contains=["stable", "spike"])
    assert {s.file_id for s in result} == {"0001", "0003"}


def test_filter_by_notes_contains_list_case_insensitive(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(notes_contains=["STABLE", "SPIKE"])
    assert {s.file_id for s in result} == {"0001", "0003"}


def test_filter_by_notes_contains_list_empty_falls_back_to_no_filter(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(notes_contains=[])
    assert {s.file_id for s in result} == {"0001", "0002", "0003", "0004"}


def test_filter_by_notes_contains_list_skips_blank_entries(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(notes_contains=["   ", "spike"])
    assert {s.file_id for s in result} == {"0003"}


def test_filters_compose(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(
        sensor_type="voltage",
        voltage_range="230-240",
        humidity_range="0-50",
    )
    assert {s.file_id for s in result} == {"0001", "0004"}


def test_filter_by_ids(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(ids=["0001", "0003"])
    assert {s.file_id for s in result} == {"0001", "0003"}


def test_filter_by_ids_combines_with_type(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(ids=["0001", "0002", "0003"], sensor_type="voltage")
    assert {s.file_id for s in result} == {"0001", "0002"}


def test_filter_by_ids_empty_list_is_noop(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(ids=[])
    # empty list → no filter applied (same semantics as None) — matches all
    assert len(result) == 4


def test_filter_by_ids_unknown_returns_empty(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_sensors(ids=["does-not-exist"])
    assert result == []


def test_get_broken_sensors_flags_unexpected_field(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    result = service.get_broken_sensors("temperature")
    # 0001 + 0004 are temperature/voltage but populate humidity_percent → broken
    assert {s.file_id for s in result} == {"0001", "0004"}


def test_get_broken_sensors_multi_type_allows_all_declared_fields(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    # 0002 is voltage/water → voltage_supply_v + water_level_meters allowed, rest zero
    result = service.get_broken_sensors("water")
    assert result == []


def test_get_broken_sensors_filters_by_type(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    # 0003 is pressure type but has humidity_percent=90 → broken
    result = service.get_broken_sensors("pressure")
    assert {s.file_id for s in result} == {"0003"}


def test_get_broken_sensors_ignores_other_types(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    # voltage filter pulls 0001, 0002, 0004 — 0001 + 0004 broken via humidity
    result = service.get_broken_sensors("voltage")
    assert {s.file_id for s in result} == {"0001", "0004"}


def test_get_broken_sensors_empty_when_no_match(sensors_dir: Path) -> None:
    service = SensorService(sensors_dir=sensors_dir)
    assert service.get_broken_sensors("nonexistent") == []


def test_missing_sensors_dir_raises(tmp_path: Path) -> None:
    service = SensorService(sensors_dir=tmp_path / "missing")
    with pytest.raises(FileNotFoundError):
        service.load_sensors()
