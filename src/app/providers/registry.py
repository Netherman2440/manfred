from __future__ import annotations

from dataclasses import dataclass

from app.providers.base import Provider


@dataclass(slots=True, frozen=True)
class ResolvedProvider:
    provider: Provider
    model: str


class ProviderRegistry:
    def __init__(self, providers: dict[str, Provider]) -> None:
        self._providers = providers

    def resolve(self, model_ref: str) -> ResolvedProvider | None:
        if ":" not in model_ref:
            provider = self._providers.get("openrouter")
            if provider is None:
                return None
            return ResolvedProvider(provider=provider, model=model_ref)

        provider_name, model = model_ref.split(":", 1)
        provider = self._providers.get(provider_name)
        if provider is None or not model:
            return None

        return ResolvedProvider(provider=provider, model=model)
