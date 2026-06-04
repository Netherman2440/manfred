from __future__ import annotations

import json
from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext
from app.services.sensors import BaseSensorService

DEFAULT_LIMIT = 50
MAX_LIMIT = 500

ALLOWED_ARGS: tuple[str, ...] = (
    "ids",
    "sensor_type",
    "temp_range",
    "pressure_range",
    "water_range",
    "voltage_range",
    "humidity_range",
    "notes_contains",
    "limit",
)

ARG_ALIASES: dict[str, str] = {
    "id": "ids",
    "file_id": "ids",
    "file_ids": "ids",
    "sensor_id": "ids",
    "sensor_ids": "ids",
    "temperature_range": "temp_range",
    "temperature_k_range": "temp_range",
    "temperature_K_range": "temp_range",
    "temp": "temp_range",
    "temperature": "temp_range",
    "pressure_bar_range": "pressure_range",
    "pressure": "pressure_range",
    "water_level_range": "water_range",
    "water_level_meters_range": "water_range",
    "water_meters_range": "water_range",
    "water": "water_range",
    "voltage_supply_range": "voltage_range",
    "voltage_supply_v_range": "voltage_range",
    "voltage_v_range": "voltage_range",
    "voltage": "voltage_range",
    "humidity_percent_range": "humidity_range",
    "humidity": "humidity_range",
    "notes": "notes_contains",
    "operator_notes": "notes_contains",
    "operator_notes_contains": "notes_contains",
    "type": "sensor_type",
    "sensor_types": "sensor_type",
}

ARGS_FORMAT_HINT = (
    "Accepted arguments (all optional):\n"
    "  - ids                (array of strings) exact file_id match, e.g. ['0001', '0042']\n"
    "  - sensor_type        (string) e.g. 'voltage', 'water', 'temperature', 'pressure', 'humidity'\n"
    "  - temp_range         (string) range over temperature_K\n"
    "  - pressure_range     (string) range over pressure_bar\n"
    "  - water_range        (string) range over water_level_meters\n"
    "  - voltage_range      (string) range over voltage_supply_v\n"
    "  - humidity_range     (string) range over humidity_percent\n"
    "  - notes_contains     (string OR array of strings) case-insensitive substring(s) of operator_notes; array = match ANY (OR)\n"
    "  - limit              (integer) max sensors returned (default 50, max 500)\n"
    "Common typos: 'temperature_K_range' -> 'temp_range'; 'pressure_bar_range' -> 'pressure_range'; "
    "'water_level_meters_range' -> 'water_range'; 'voltage_supply_v_range' -> 'voltage_range'; "
    "'humidity_percent_range' -> 'humidity_range'. Do NOT invent new arg names — only the nine above are accepted."
)

RANGE_FORMAT_HINT = (
    "Range format: comma-separated segments. Each segment is one of:\n"
    "  - 'low-high'  inclusive range, e.g. '200-300' (both bounds, low <= high)\n"
    "  - 'low-'      open upper bound, e.g. '600-' means value >= 600\n"
    "  - '-high'     open lower bound, e.g. '-10' means value <= 10\n"
    "  - 'value'     single number, e.g. '230' means value == 230\n"
    "Multiple segments are unioned with commas: '1-3, 7-10' matches [1..3] OR [7..10].\n"
    "More examples:\n"
    "  '-3, 10-'   value <= 3 OR value >= 10\n"
    "  '229-231'   voltage between 229 and 231 inclusive\n"
    "  '0-0'       value exactly 0 (also written as '0')\n"
    "Disallowed: empty string, lone '-', 'high-low' (low must be <= high), non-numeric tokens."
)


def _normalize_optional_str(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{name}' must be a string or null")
    stripped = value.strip()
    return stripped or None


def _normalize_notes_contains(value: Any) -> str | list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, list):
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("'notes_contains' must be a string or a list of strings")
            stripped = item.strip()
            if stripped:
                cleaned.append(stripped)
        return cleaned or None
    raise ValueError("'notes_contains' must be a string or a list of strings")


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


def build_get_sensors_tool(sensor_service: BaseSensorService) -> Tool:
    async def handle_get_sensors(
        args: dict[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, bool | str]:
        del context

        unknown = _check_unknown_args(args)
        if unknown is not None:
            unknown_repr, suggestions = unknown
            error = f"Unknown argument(s): {unknown_repr}. Only fixed argument names are accepted."
            response: dict[str, Any] = {
                "ok": False,
                "error": error,
                "hint": ARGS_FORMAT_HINT,
            }
            if suggestions:
                response["did_you_mean"] = suggestions
            return response

        raw_ids = args.get("ids")
        ids: list[str] | None
        if raw_ids is None:
            ids = None
        elif isinstance(raw_ids, list):
            if not all(isinstance(x, str) and x.strip() for x in raw_ids):
                return {
                    "ok": False,
                    "error": "'ids' must be a list of non-empty strings",
                    "hint": ARGS_FORMAT_HINT,
                }
            ids = [x.strip() for x in raw_ids] or None
        else:
            return {
                "ok": False,
                "error": "'ids' must be an array of strings",
                "hint": ARGS_FORMAT_HINT,
            }

        try:
            sensor_type = _normalize_optional_str(args.get("sensor_type"), "sensor_type")
            temp_range = _normalize_optional_str(args.get("temp_range"), "temp_range")
            pressure_range = _normalize_optional_str(args.get("pressure_range"), "pressure_range")
            water_range = _normalize_optional_str(args.get("water_range"), "water_range")
            voltage_range = _normalize_optional_str(args.get("voltage_range"), "voltage_range")
            humidity_range = _normalize_optional_str(args.get("humidity_range"), "humidity_range")
            notes_contains = _normalize_notes_contains(args.get("notes_contains"))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        raw_limit = args.get("limit", DEFAULT_LIMIT)
        if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
            return {
                "ok": False,
                "error": "'limit' must be an integer",
                "hint": ARGS_FORMAT_HINT,
            }
        limit = max(1, min(MAX_LIMIT, raw_limit))

        try:
            matches = sensor_service.get_sensors(
                ids=ids,
                sensor_type=sensor_type,
                temp_range=temp_range,
                pressure_range=pressure_range,
                water_range=water_range,
                voltage_range=voltage_range,
                humidity_range=humidity_range,
                notes_contains=notes_contains,
            )
        except ValueError as exc:
            return {
                "ok": False,
                "error": f"Invalid range argument: {exc}",
                "hint": RANGE_FORMAT_HINT,
            }
        except FileNotFoundError as exc:
            return {"ok": False, "error": f"Sensor data unavailable: {exc}"}

        truncated = len(matches) > limit
        page = matches[:limit]
        payload: dict[str, Any] = {
            "total_matches": len(matches),
            "returned": len(page),
            "truncated": truncated,
            "sensors": [
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
                for s in page
            ],
        }
        if truncated:
            payload["hint"] = (
                f"Showing first {limit} of {len(matches)} matches. "
                "Tighten filters (narrower range, more specific sensor_type or notes_contains) "
                "or raise 'limit' (max 500) to see more."
            )

        return {"ok": True, "output": json.dumps(payload, ensure_ascii=False)}

    description = (
        "Query a fixed in-memory dataset of ~10,000 sensor readings. "
        "STRICT ARG NAMES — only the following keys are accepted: "
        "'ids', 'sensor_type', 'temp_range', 'pressure_range', 'water_range', 'voltage_range', "
        "'humidity_range', 'notes_contains', 'limit'. "
        "Range arg names DO NOT include the unit suffix — use 'temp_range' (NOT 'temperature_K_range'), "
        "'pressure_range' (NOT 'pressure_bar_range'), 'water_range' (NOT 'water_level_meters_range'), "
        "'voltage_range' (NOT 'voltage_supply_v_range'), 'humidity_range' (NOT 'humidity_percent_range'). "
        "Unknown argument names return an error with a suggested correction. "
        "Each reading has: sensor_types (list, e.g. ['voltage', 'water']), timestamp, "
        "temperature_K, pressure_bar, water_level_meters, voltage_supply_v, humidity_percent, operator_notes. "
        "All filter arguments are OPTIONAL — omit them to match everything. "
        "Returns 'total_matches' plus a capped page of sensor objects.\n\n"
        "Filters:\n"
        "  - ids: array of exact file_id strings (e.g. ['0001', '0042']). When provided, "
        "only sensors with matching file_id are returned. Combines (AND) with other filters.\n"
        "  - sensor_type: substring matched against each entry in the sensor_types list "
        "(case-insensitive, exact token match, e.g. 'voltage' matches ['voltage', 'water']).\n"
        "  - temp_range / pressure_range / water_range / voltage_range / humidity_range: "
        "page-style numeric ranges over the matching field. See RANGE FORMAT below.\n"
        "  - notes_contains: case-insensitive substring of operator_notes. Accepts a single string OR "
        "an array of strings — array semantics is OR (sensor matches if ANY of the substrings is present in its notes).\n"
        "  - limit: how many sensors to return (default 50, max 500). Total count always reported.\n\n"
        f"RANGE FORMAT:\n{RANGE_FORMAT_HINT}"
    )

    return Tool(
        type="sync",
        definition=FunctionToolDefinition(
            name="get_sensors",
            description=description,
            parameters={
                "type": "object",
                "properties": {
                    "ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional. Exact file_id matches, e.g. ['0001', '0042']. Combines with other filters (AND)."
                        ),
                    },
                    "sensor_type": {
                        "type": "string",
                        "description": (
                            "Optional. Token to match against sensor_types list, "
                            "e.g. 'voltage', 'water', 'temperature', 'pressure'. Case-insensitive."
                        ),
                    },
                    "temp_range": {
                        "type": "string",
                        "description": (
                            "Optional. Range over temperature_K (Kelvin). "
                            "Examples: '600-', '-100', '273-373', '-3, 10-'."
                        ),
                    },
                    "pressure_range": {
                        "type": "string",
                        "description": "Optional. Range over pressure_bar. Same format as temp_range.",
                    },
                    "water_range": {
                        "type": "string",
                        "description": "Optional. Range over water_level_meters. Same format as temp_range.",
                    },
                    "voltage_range": {
                        "type": "string",
                        "description": (
                            "Optional. Range over voltage_supply_v. Same format as temp_range, "
                            "e.g. '229-231' for voltages between 229V and 231V inclusive."
                        ),
                    },
                    "humidity_range": {
                        "type": "string",
                        "description": "Optional. Range over humidity_percent (0..100). Same format as temp_range.",
                    },
                    "notes_contains": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                        "description": (
                            "Optional. Case-insensitive substring of operator_notes. "
                            "Pass a single string for one substring, or an array of strings "
                            "(e.g. ['faulty', 'replace', 'out of spec']) to match ANY (OR) — "
                            "a sensor is returned if its notes contain at least one of the substrings."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_LIMIT,
                        "description": f"Max sensors returned. Default {DEFAULT_LIMIT}, max {MAX_LIMIT}.",
                    },
                },
                "additionalProperties": False,
            },
        ),
        handler=handle_get_sensors,
    )
