from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SensorReading:
    file_id: str
    sensor_types: tuple[str, ...]
    timestamp: int
    temperature_K: float
    pressure_bar: float
    water_level_meters: float
    voltage_supply_v: float
    humidity_percent: float
    operator_notes: str
