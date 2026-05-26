from __future__ import annotations

import csv
import logging
import threading
from pathlib import Path

from app.services.aidevs.negotiations.base import BaseNegotiationsService
from app.services.aidevs.negotiations.models import City, Connection, ItemsPage, ItemToSell

logger = logging.getLogger("app.services.aidevs.negotiations")


class NegotiationsService(BaseNegotiationsService):
    def __init__(self, *, csv_dir: Path) -> None:
        self._csv_dir = Path(csv_dir)
        self._loaded = False
        self._cities: list[City] = []
        self._items: list[ItemToSell] = []
        self._connections: list[Connection] = []
        self._cities_by_name: dict[str, City] = {}
        self._items_by_name: dict[str, ItemToSell] = {}
        self._cities_by_code: dict[str, City] = {}
        self._items_by_code: dict[str, ItemToSell] = {}
        self._item_codes_by_city_code: dict[str, list[str]] = {}
        self._city_codes_by_item_code: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            self._cities = self._load_cities()
            self._items = self._load_items()
            self._connections = self._load_connections()
            self._build_indexes()
            self._loaded = True
            logger.info(
                "Loaded negotiations data from %s: %d cities, %d items, %d connections",
                self._csv_dir,
                len(self._cities),
                len(self._items),
                len(self._connections),
            )

    def get_items_for_city(
        self,
        city_name: str,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> ItemsPage:
        if not self._loaded:
            self.load()
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        if limit is not None and limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")

        empty = ItemsPage(items=[], total=0, offset=offset, limit=limit)
        key = city_name.strip().lower()
        if not key:
            return empty
        city = self._cities_by_name.get(key)
        if city is None:
            return empty
        item_codes = self._item_codes_by_city_code.get(city.city_code, [])
        items = [self._items_by_code[code] for code in item_codes if code in self._items_by_code]
        total = len(items)
        end = total if limit is None else offset + limit
        page = items[offset:end]
        return ItemsPage(items=page, total=total, offset=offset, limit=limit)

    def get_cities_for_item(self, item_name: str) -> list[City]:
        if not self._loaded:
            self.load()
        key = item_name.strip().lower()
        if not key:
            return []
        item = self._items_by_name.get(key)
        if item is None:
            return []
        city_codes = self._city_codes_by_item_code.get(item.item_code, [])
        return [self._cities_by_code[code] for code in city_codes if code in self._cities_by_code]

    def search_cities(self, query: str, *, limit: int = 10) -> list[City]:
        if not self._loaded:
            self.load()
        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        needle = query.strip().lower()
        if not needle:
            return []
        matches = [c for c in self._cities if needle in c.name.lower()]
        return matches[:limit]

    def search_items(self, query: str, *, limit: int = 10) -> list[ItemToSell]:
        if not self._loaded:
            self.load()
        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")
        needle = query.strip().lower()
        if not needle:
            return []
        matches = [i for i in self._items if needle in i.name.lower()]
        return matches[:limit]

    def _load_cities(self) -> list[City]:
        path = self._csv_dir / "cities.csv"
        if not path.is_file():
            raise FileNotFoundError(f"Cities CSV not found: {path}")
        cities: list[City] = []
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                cities.append(City(name=row["name"], city_code=row["code"]))
        return cities

    def _load_items(self) -> list[ItemToSell]:
        path = self._csv_dir / "items.csv"
        if not path.is_file():
            raise FileNotFoundError(f"Items CSV not found: {path}")
        items: list[ItemToSell] = []
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                items.append(ItemToSell(name=row["name"], item_code=row["code"]))
        return items

    def _load_connections(self) -> list[Connection]:
        path = self._csv_dir / "connections.csv"
        if not path.is_file():
            raise FileNotFoundError(f"Connections CSV not found: {path}")
        connections: list[Connection] = []
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                connections.append(
                    Connection(item_code=row["itemCode"], city_code=row["cityCode"])
                )
        return connections

    def _build_indexes(self) -> None:
        self._cities_by_name = {c.name.strip().lower(): c for c in self._cities}
        self._items_by_name = {i.name.strip().lower(): i for i in self._items}
        self._cities_by_code = {c.city_code: c for c in self._cities}
        self._items_by_code = {i.item_code: i for i in self._items}

        item_codes_by_city: dict[str, list[str]] = {}
        city_codes_by_item: dict[str, list[str]] = {}
        for conn in self._connections:
            item_codes_by_city.setdefault(conn.city_code, []).append(conn.item_code)
            city_codes_by_item.setdefault(conn.item_code, []).append(conn.city_code)
        self._item_codes_by_city_code = item_codes_by_city
        self._city_codes_by_item_code = city_codes_by_item
