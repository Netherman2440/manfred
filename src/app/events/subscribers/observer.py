from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from app.config import Settings
from app.events import EventBus, TurnCompletedEvent
from app.runtime.background_tasks import BackgroundTaskRegistry
from app.services.memory.observe_use_case import ObserveUseCase

logger = logging.getLogger(__name__)


class ObserverSubscriber:
    """Schedules background observations after each agent turn.

    The EventBus handler is synchronous so we fire-and-forget via
    asyncio.create_task on the running loop.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        observe_use_case: ObserveUseCase,
        background_task_registry: BackgroundTaskRegistry,
    ) -> None:
        self._settings = settings
        self._observe_use_case = observe_use_case
        self._background_task_registry = background_task_registry

    def subscribe(self, event_bus: EventBus) -> Callable[[], None]:
        return event_bus.subscribe("turn.completed", self._handle)

    def _handle(self, event: TurnCompletedEvent) -> None:
        if not self._settings.OBSERVATIONAL_MEMORY_ENABLED:
            return
        if not event.ctx.agent_name:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("No running loop for ObserverSubscriber; skipping.")
            return
        self._background_task_registry.schedule(self._observe_async(event))

    async def _observe_async(self, event: TurnCompletedEvent) -> None:
        try:
            await self._observe_use_case.execute(
                session_id=event.ctx.session_id,
                agent_run_id=event.ctx.agent_id,
                force=False,
            )
        except Exception:
            logger.exception(
                "Observer failed for agent %s (session %s)",
                event.ctx.agent_id,
                event.ctx.session_id,
            )
