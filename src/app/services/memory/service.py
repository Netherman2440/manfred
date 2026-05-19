from __future__ import annotations

import re

from app.domain import Item
from app.providers import Provider
from app.providers.types import ProviderMessageInputItem, ProviderRequest
from app.services.memory.base import BaseMemoryService
from app.services.memory.message_formatter import format_items_for_memory
from app.services.memory.models import ObservationResult
from app.services.memory.prompts import observe_prompt, reflect_prompt


class MemoryService(BaseMemoryService):
    """Wraps observer/reflector LLM calls.

    The observer reads existing memory.md + new items, returns structured
    observations and (optionally) an updated current_task. The reflector
    consolidates an over-long memory log.
    """

    def __init__(self, *, provider: Provider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def observe(
        self,
        *,
        existing_observations: str | None,
        items: list[Item],
    ) -> ObservationResult:
        formatted = format_items_for_memory(items)
        if existing_observations:
            user_content = (
                f"<existing-observations>\n{existing_observations}\n</existing-observations>\n\n"
                f"<new-messages>\n{formatted}\n</new-messages>"
            )
        else:
            user_content = formatted

        response = await self._provider.generate(
            ProviderRequest(
                model=self._model,
                instructions=observe_prompt(),
                input=[ProviderMessageInputItem(role="user", content=user_content)],
            )
        )
        content = _extract_text(response)
        return ObservationResult(
            observations=_extract_tag(content, "observations") or content,
            current_task=_extract_tag(content, "current-task"),
        )

    async def reflect(self, observations: str) -> str:
        response = await self._provider.generate(
            ProviderRequest(
                model=self._model,
                instructions=reflect_prompt(),
                input=[ProviderMessageInputItem(role="user", content=observations)],
            )
        )
        content = _extract_text(response)
        return _extract_tag(content, "observations") or content


def _extract_text(response) -> str:  # noqa: ANN001
    from app.providers.types import ProviderTextOutputItem

    return "".join(item.text for item in response.output if isinstance(item, ProviderTextOutputItem) and item.text)


def _extract_tag(content: str, tag: str) -> str | None:
    pattern = rf"<{re.escape(tag)}>(.*?)</{re.escape(tag)}>"
    match = re.search(pattern, content, re.DOTALL)
    return match.group(1).strip() if match else None
