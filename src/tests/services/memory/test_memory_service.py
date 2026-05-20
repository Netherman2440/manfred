import pytest

from app.providers.types import (
    ProviderRequest,
    ProviderResponse,
    ProviderTextOutputItem,
    ProviderUsage,
)
from app.services.memory.service import MemoryService


class FakeProvider:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.last_request: ProviderRequest | None = None

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.last_request = request
        return ProviderResponse(
            output=[ProviderTextOutputItem(text=self._response_text)],
            usage=ProviderUsage(),
        )

    async def stream(self, request: ProviderRequest):  # pragma: no cover - unused
        raise NotImplementedError


@pytest.mark.asyncio
async def test_observe_parses_xml_tags() -> None:
    response = (
        "<observations>\n"
        "* 🔴 (14:30) User loves dinosaurs\n"
        "</observations>\n"
        "<current-task>\n"
        "Drawing a dinosaur\n"
        "</current-task>\n"
    )
    provider = FakeProvider(response)
    service = MemoryService(provider=provider, model="test/model")

    result = await service.observe(existing_observations=None, items=[])

    assert "User loves dinosaurs" in result.observations
    assert result.current_task == "Drawing a dinosaur"


@pytest.mark.asyncio
async def test_observe_falls_back_to_raw_content_when_no_tags() -> None:
    provider = FakeProvider("just plain text")
    service = MemoryService(provider=provider, model="test/model")

    result = await service.observe(existing_observations=None, items=[])

    assert result.observations == "just plain text"
    assert result.current_task is None


@pytest.mark.asyncio
async def test_observe_includes_existing_in_human_message() -> None:
    provider = FakeProvider("<observations>new</observations>")
    service = MemoryService(provider=provider, model="test/model")

    await service.observe(existing_observations="prior", items=[])

    assert provider.last_request is not None
    contents = [item.content for item in provider.last_request.input if getattr(item, "content", None)]
    assert any("<existing-observations>" in content for content in contents)
    assert any("prior" in content for content in contents)


@pytest.mark.asyncio
async def test_reflect_extracts_observations_tag() -> None:
    provider = FakeProvider("<observations>distilled</observations>")
    service = MemoryService(provider=provider, model="test/model")

    result = await service.reflect("old log")

    assert result == "distilled"
