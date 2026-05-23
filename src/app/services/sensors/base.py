from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.sensors.models import SensorReading


class BaseSensorService(ABC):
    @abstractmethod
    def load_sensors(self) -> None: ...

    @abstractmethod
    def get_sensors(
        self,
        *,
        ids: list[str] | None = None,
        sensor_type: str | None = None,
        temp_range: str | None = None,
        pressure_range: str | None = None,
        water_range: str | None = None,
        voltage_range: str | None = None,
        humidity_range: str | None = None,
        notes_contains: str | list[str] | None = None,
    ) -> list[SensorReading]: ...

    @abstractmethod
    def get_broken_sensors(
        self,
        sensor_type: str
    ) -> list[SensorReading]: ...
