from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.aidevs.negotiations.models import City, ItemsPage, ItemToSell


class BaseNegotiationsService(ABC):
    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def get_items_for_city(
        self,
        city_name: str,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> ItemsPage: ...

    @abstractmethod
    def get_cities_for_item(self, item_name: str) -> list[City]: ...

    @abstractmethod
    def search_cities(self, query: str, *, limit: int = 10) -> list[City]: ...

    @abstractmethod
    def search_items(self, query: str, *, limit: int = 10) -> list[ItemToSell]: ...
