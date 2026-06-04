from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class City:
    name: str
    city_code: str


@dataclass(frozen=True, slots=True)
class ItemToSell:
    name: str
    item_code: str


@dataclass(frozen=True, slots=True)
class Connection:
    item_code: str
    city_code: str


@dataclass(frozen=True, slots=True)
class ItemsPage:
    items: list[ItemToSell]
    total: int
    offset: int
    limit: int | None
