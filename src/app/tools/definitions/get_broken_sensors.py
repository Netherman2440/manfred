from __future__ import annotations

import json
from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext
from app.services.sensors import BaseSensorService

ALLOWED_ARGS: tuple[str, ...] = ("sensor_type",)

ARG_ALIASES: dict[str, str] = {
    "type": "sensor_type",
    "sensor_types": "sensor_type",
}

ARGS_FORMAT_HINT = (
    "Required argument:\n"
    "  - sensor_type (string) e.g. 'voltage', 'water', 'temperature', 'pressure', 'humidity'\n"
    "No other arguments accepted."
)


def _check_unknown_args(args: dict[str, Any]) -> tuple[str, dict[str, str]] | None:
    unknown = [k for k in args if k not in ALLOWED_ARGS]
    if not unknown:
        return None
    suggestions: dict[str, str] = {}
    for key in unknown:
        canonical = ARG_ALIASES.get(key) or ARG_ALIASES.get(key.lower())
        if canonical is not None:
            suggestions[key] = canonical
    return ", ".join(repr(k) for k in unknown), suggestions


def build_get_broken_sensors_tool(sensor_service: BaseSensorService) -> Tool:
    async def handle_get_broken_sensors(
        args: dict[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, bool | str]:
        del context

        unknown = _check_unknown_args(args)
        if unknown is not None:
            unknown_repr, suggestions = unknown
            error = f"Unknown argument(s): {unknown_repr}. Only 'sensor_type' is accepted."
            response: dict[str, Any] = {
                "ok": False,
                "error": error,
                "hint": ARGS_FORMAT_HINT,
            }
            if suggestions:
                response["did_you_mean"] = suggestions
            return response

        raw_type = args.get("sensor_type")
        if not isinstance(raw_type, str) or not raw_type.strip():
            return {
                "ok": False,
                "error": "'sensor_type' is required and must be a non-empty string",
                "hint": ARGS_FORMAT_HINT,
            }
        sensor_type = raw_type.strip()

        try:
            matches = sensor_service.get_broken_sensors(sensor_type)
        except FileNotFoundError as exc:
            return {"ok": False, "error": f"Sensor data unavailable: {exc}"}

        payload: dict[str, Any] = {
            "queried_type": sensor_type.lower(),
            "broken_count": len(matches),
            "broken_sensors": [
                {
                    "file_id": s.file_id,
                    "sensor_types": list(s.sensor_types),
                    "timestamp": s.timestamp,
                    "temperature_K": s.temperature_K,
                    "pressure_bar": s.pressure_bar,
                    "water_level_meters": s.water_level_meters,
                    "voltage_supply_v": s.voltage_supply_v,
                    "humidity_percent": s.humidity_percent,
                    "operator_notes": s.operator_notes,
                }
                for s in matches
            ],
        }
        return {"ok": True, "output": json.dumps(payload, ensure_ascii=False)}

    description = (
        "Return sensors of a given type whose readings populate fields they should NOT — "
        "the s03e01 anomaly: a sensor declared as e.g. 'temperature' is broken if it also "
        "carries non-zero values in unrelated fields (pressure_bar, water_level_meters, etc.). "
        "Multi-type sensors are respected: a 'voltage/water' sensor may legitimately populate "
        "BOTH voltage_supply_v and water_level_meters; only the remaining fields must be zero.\n\n"
        "Argument: sensor_type (required, case-insensitive). Matches against the sensor's "
        "sensor_types list. Valid tokens: 'temperature', 'pressure', 'water', 'voltage', 'humidity'.\n\n"
        "Returns: queried_type, broken_count, and broken_sensors (list of full sensor objects)."
    )

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="get_broken_sensors",
            description=description,
            parameters={
                "type": "object",
                "properties": {
                    "sensor_type": {
                        "type": "string",
                        "description": (
                            "Required. Token to match against sensor_types list, "
                            "e.g. 'voltage', 'water', 'temperature', 'pressure', 'humidity'. "
                            "Case-insensitive."
                        ),
                    },
                },
                "required": ["sensor_type"],
                "additionalProperties": False,
            },
        ),
        handler=handle_get_broken_sensors,
    )
