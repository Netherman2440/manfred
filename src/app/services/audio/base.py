from __future__ import annotations

from abc import ABC, abstractmethod


class AudioService(ABC):
    @abstractmethod
    async def transcribe_audio(self, path: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def generate_audio(self, text: str) -> str:
        raise NotImplementedError
