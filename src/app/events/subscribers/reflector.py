from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session as DbSession

from app.config import Settings
from app.domain.repositories import SessionRepository
from app.events import (
    EventBus,
    ObservationSuccessEvent,
    ReflectionStartedEvent,
    ReflectionSuccessEvent,
)
from app.runtime.background_tasks import BackgroundTaskRegistry
from app.services.lock_service import BaseLockService
from app.services.memory.base import BaseMemoryService
from app.services.memory.token_counter import MemoryTokenCounter

logger = logging.getLogger(__name__)


class ReflectorSubscriber:
    """Consolidates memory.md when it grows past TOKENS_TO_REFLECT.

    Triggered by `observation.success` events. Reuses the per-(user, agent_name)
    lock so reflection cannot race with another observation/reflection on the
    same memory log.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: Callable[[], DbSession],
        memory_service: BaseMemoryService,
        token_counter: MemoryTokenCounter,
        event_bus: EventBus,
        lock_service: BaseLockService,
        memory_path_resolver: Callable[[str, str], Path],
        background_task_registry: BackgroundTaskRegistry,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._memory_service = memory_service
        self._token_counter = token_counter
        self._event_bus = event_bus
        self._lock_service = lock_service
        self._memory_path_resolver = memory_path_resolver
        self._background_task_registry = background_task_registry

    def subscribe(self, event_bus: EventBus) -> Callable[[], None]:
        return event_bus.subscribe("observation.success", self._handle)

    def _handle(self, event: ObservationSuccessEvent) -> None:
        if not self._settings.OBSERVATIONAL_MEMORY_ENABLED:
            return
        if not event.agent_name:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._background_task_registry.schedule(self._reflect_async(event))

    async def _reflect_async(self, event: ObservationSuccessEvent) -> None:
        user_id = self._resolve_user_id(event.ctx.session_id)
        if user_id is None:
            return
        memory_path = self._memory_path_resolver(user_id, event.agent_name)
        try:
            content = memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""
        except OSError as exc:
            logger.warning(
                "Failed to read memory file for agent %s (session %s): %s",
                event.agent_name,
                event.ctx.session_id,
                exc,
            )
            return
        if not content:
            return

        token_count = self._token_counter.count_text(content)
        if token_count < self._settings.TOKENS_TO_REFLECT:
            return

        lock = await self._lock_service.get(user_id, event.agent_name)
        async with lock:
            self._event_bus.emit(
                ReflectionStartedEvent(
                    ctx=event.ctx,
                    agent_name=event.agent_name,
                    token_count=token_count,
                )
            )
            try:
                reflected = await self._memory_service.reflect(content)
            except Exception:
                logger.exception(
                    "Reflector failed for agent %s (session %s)",
                    event.agent_name,
                    event.ctx.session_id,
                )
                return
            if not reflected or not reflected.strip():
                logger.warning(
                    "Reflector produced empty result for agent %s (session %s); skipping write",
                    event.agent_name,
                    event.ctx.session_id,
                )
                return
            new_count = self._token_counter.count_text(reflected)
            if new_count >= token_count:
                logger.warning(
                    "Reflector did not reduce token count for agent %s (session %s): %d -> %d; skipping write",
                    event.agent_name,
                    event.ctx.session_id,
                    token_count,
                    new_count,
                )
                return
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            memory_path.write_text(reflected.strip() + "\n", encoding="utf-8")
            self._event_bus.emit(
                ReflectionSuccessEvent(
                    ctx=event.ctx,
                    agent_name=event.agent_name,
                    token_count=new_count,
                )
            )

    def _resolve_user_id(self, session_id: str) -> str | None:
        sa_session = self._session_factory()
        try:
            session = SessionRepository(sa_session).get(session_id)
            return session.user_id if session is not None else None
        finally:
            sa_session.close()
