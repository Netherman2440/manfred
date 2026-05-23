import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.domain.tool import ToolExecutionContext
from app.services.sensors import SensorService
from app.tools.definitions.get_sensors import (
    ARGS_FORMAT_HINT,
    RANGE_FORMAT_HINT,
    build_get_sensors_tool,
)


def _write_sensor(directory: Path, file_id: str, **overrides: Any) -> None:
    payload = {
        "sensor_type": "temperature/voltage",
        "timestamp": 1774064280,
        "temperature_K": 300.0,
        "pressure_bar": 0.0,
        "water_level_meters": 0.0,
        "voltage_supply_v": 230.0,
        "humidity_percent": 30.0,
        "operator_notes": "stable",
    }
    payload.update(overrides)
    (directory / f"{file_id}.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def sensor_tool(tmp_path: Path):
    directory = tmp_path / "sensors"
    directory.mkdir()
    _write_sensor(directory, "0001", sensor_type="voltage", temperature_K=250.0)
    _write_sensor(directory, "0002", sensor_type="water/voltage", temperature_K=400.0)
    _write_sensor(directory, "0003", sensor_type="pressure", temperature_K=700.0)
    service = SensorService(sensors_dir=directory)
    return build_get_sensors_tool(service)


@pytest.fixture
def context() -> ToolExecutionContext:
    return MagicMock(spec=ToolExecutionContext)


@pytest.mark.asyncio
async def test_returns_all_sensors_when_no_filters(sensor_tool, context) -> None:
    result = await sensor_tool.handler({}, context)
    assert result["ok"] is True
    payload = json.loads(result["output"])
    assert payload["total_matches"] == 3
    assert payload["returned"] == 3
    assert payload["truncated"] is False
    assert [s["file_id"] for s in payload["sensors"]] == ["0001", "0002", "0003"]


@pytest.mark.asyncio
async def test_filters_by_range(sensor_tool, context) -> None:
    result = await sensor_tool.handler({"temp_range": "600-"}, context)
    assert result["ok"] is True
    payload = json.loads(result["output"])
    assert payload["total_matches"] == 1
    assert payload["sensors"][0]["file_id"] == "0003"


@pytest.mark.asyncio
async def test_invalid_range_returns_hint(sensor_tool, context) -> None:
    result = await sensor_tool.handler({"temp_range": "abc"}, context)
    assert result["ok"] is False
    assert "Invalid range argument" in result["error"]
    assert result["hint"] == RANGE_FORMAT_HINT


@pytest.mark.asyncio
async def test_invalid_range_swapped_bounds_returns_hint(sensor_tool, context) -> None:
    result = await sensor_tool.handler({"voltage_range": "300-100"}, context)
    assert result["ok"] is False
    assert "Invalid range argument" in result["error"]
    assert "low <= high" in result["hint"]


@pytest.mark.asyncio
async def test_limit_truncates_with_hint(sensor_tool, context) -> None:
    result = await sensor_tool.handler({"limit": 2}, context)
    payload = json.loads(result["output"])
    assert payload["total_matches"] == 3
    assert payload["returned"] == 2
    assert payload["truncated"] is True
    assert "hint" in payload


@pytest.mark.asyncio
async def test_limit_must_be_integer(sensor_tool, context) -> None:
    result = await sensor_tool.handler({"limit": "five"}, context)
    assert result["ok"] is False
    assert "limit" in result["error"]


@pytest.mark.asyncio
async def test_sensor_type_filter(sensor_tool, context) -> None:
    result = await sensor_tool.handler({"sensor_type": "water"}, context)
    payload = json.loads(result["output"])
    assert payload["total_matches"] == 1
    assert payload["sensors"][0]["file_id"] == "0002"


@pytest.mark.asyncio
async def test_unknown_arg_with_known_alias_suggests_correction(sensor_tool, context) -> None:
    result = await sensor_tool.handler(
        {"sensor_type": "temperature", "temperature_K_range": "900-1000", "limit": 500},
        context,
    )
    assert result["ok"] is False
    assert "Unknown argument" in result["error"]
    assert "'temperature_K_range'" in result["error"]
    assert result["hint"] == ARGS_FORMAT_HINT
    assert result["did_you_mean"] == {"temperature_K_range": "temp_range"}


@pytest.mark.asyncio
async def test_unknown_arg_without_alias_still_errors(sensor_tool, context) -> None:
    result = await sensor_tool.handler({"completely_unknown": "x"}, context)
    assert result["ok"] is False
    assert "'completely_unknown'" in result["error"]
    assert result["hint"] == ARGS_FORMAT_HINT
    assert "did_you_mean" not in result


@pytest.mark.asyncio
async def test_multiple_typo_aliases_suggested(sensor_tool, context) -> None:
    result = await sensor_tool.handler(
        {"pressure_bar_range": "0-50", "water_level_meters_range": "0-5"},
        context,
    )
    assert result["ok"] is False
    assert result["did_you_mean"] == {
        "pressure_bar_range": "pressure_range",
        "water_level_meters_range": "water_range",
    }


@pytest.mark.asyncio
async def test_empty_string_filters_treated_as_none(sensor_tool, context) -> None:
    result = await sensor_tool.handler({"sensor_type": "", "temp_range": "  "}, context)
    assert result["ok"] is True
    payload = json.loads(result["output"])
    assert payload["total_matches"] == 3
