from __future__ import annotations

from abc import ABC, abstractmethod


class ImageService(ABC):
    @abstractmethod
    async def describe_image(self, path: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def create_image(self, prompt: str) -> str:
        raise NotImplementedError
