from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from app.services.sensors.base import BaseSensorService
from app.services.sensors.models import SensorReading
from app.services.sensors.range_parser import matches_range

logger = logging.getLogger("app.services.sensors")

_TYPE_TO_FIELD: dict[str, str] = {
    "temperature": "temperature_K",
    "pressure": "pressure_bar",
    "water": "water_level_meters",
    "voltage": "voltage_supply_v",
    "humidity": "humidity_percent",
}


class SensorService(BaseSensorService):
    def __init__(self, *, sensors_dir: Path) -> None:
        self._sensors_dir = Path(sensors_dir)
        self._sensors: list[SensorReading] | None = None
        self._lock = threading.Lock()

    def load_sensors(self) -> None:
        with self._lock:
            if self._sensors is not None:
                return
            self._sensors = self._load_from_disk()
            logger.info(
                "Loaded %d sensor readings from %s",
                len(self._sensors),
                self._sensors_dir,
            )

    def get_sensors(
        self,
        *,
        sensor_type: str | None = None,
        temp_range: str | None = None,
        pressure_range: str | None = None,
        water_range: str | None = None,
        voltage_range: str | None = None,
        humidity_range: str | None = None,
        notes_contains: str | None = None,
    ) -> list[SensorReading]:
        if self._sensors is None:
            self.load_sensors()
        assert self._sensors is not None

        needle = notes_contains.lower() if notes_contains else None
        type_filter = sensor_type.lower() if sensor_type else None

        results: list[SensorReading] = []
        for sensor in self._sensors:
            if type_filter is not None and type_filter not in sensor.sensor_types:
                continue
            if temp_range is not None and not matches_range(sensor.temperature_K, temp_range):
                continue
            if pressure_range is not None and not matches_range(sensor.pressure_bar, pressure_range):
                continue
            if water_range is not None and not matches_range(sensor.water_level_meters, water_range):
                continue
            if voltage_range is not None and not matches_range(sensor.voltage_supply_v, voltage_range):
                continue
            if humidity_range is not None and not matches_range(sensor.humidity_percent, humidity_range):
                continue
            if needle is not None and needle not in sensor.operator_notes.lower():
                continue
            results.append(sensor)
        return results

    def get_broken_sensors(self, sensor_type: str) -> list[SensorReading]:
        if self._sensors is None:
            self.load_sensors()
        assert self._sensors is not None

        type_filter = sensor_type.lower()
        all_fields = set(_TYPE_TO_FIELD.values())

        results: list[SensorReading] = []
        for sensor in self._sensors:
            if type_filter not in sensor.sensor_types:
                continue
            expected = {
                _TYPE_TO_FIELD[t] for t in sensor.sensor_types if t in _TYPE_TO_FIELD
            }
            forbidden = all_fields - expected
            if any(getattr(sensor, field) for field in forbidden):
                results.append(sensor)
        return results

    def _load_from_disk(self) -> list[SensorReading]:
        if not self._sensors_dir.is_dir():
            raise FileNotFoundError(f"Sensors directory not found: {self._sensors_dir}")

        files = sorted(self._sensors_dir.glob("*.json"))
        sensors: list[SensorReading] = []
        for path in files:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            sensor_types = tuple(
                part.strip().lower()
                for part in str(data["sensor_type"]).split("/")
                if part.strip()
            )
            sensors.append(
                SensorReading(
                    file_id=path.stem,
                    sensor_types=sensor_types,
                    timestamp=int(data["timestamp"]),
                    temperature_K=float(data["temperature_K"]),
                    pressure_bar=float(data["pressure_bar"]),
                    water_level_meters=float(data["water_level_meters"]),
                    voltage_supply_v=float(data["voltage_supply_v"]),
                    humidity_percent=float(data["humidity_percent"]),
                    operator_notes=str(data["operator_notes"]),
                )
            )
        return sensors
