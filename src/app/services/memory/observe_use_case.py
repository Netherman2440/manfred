from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session as DbSession

from app.db.base import utcnow
from app.domain import Item, Session
from app.domain.repositories import (
    AgentRepository,
    ItemRepository,
    SessionRepository,
)
from app.events import (
    EventBus,
    ObservationFailureEvent,
    ObservationStartedEvent,
    ObservationSuccessEvent,
    build_event_context,
)
from app.services.lock_service import BaseLockService
from app.services.memory.base import BaseMemoryService
from app.services.memory.models import ObservationResult, ObserveOutcome
from app.services.memory.token_counter import MemoryTokenCounter

_PREVIEW_LIMIT = 200

logger = logging.getLogger(__name__)


class ObserveUseCase:
    """Orchestrates a single observation run for an (agent, session) pair.

    Owns: DB session lifecycle, lock acquisition, unobserved item filtering,
    token threshold check, LLM call, memory.md append, Session cursor update,
    and event emission.
    """

    def __init__(
        self,
        *,
        memory_service: BaseMemoryService,
        token_counter: MemoryTokenCounter,
        session_factory: Callable[[], DbSession],
        event_bus: EventBus,
        lock_service: BaseLockService,
        memory_path_resolver: Callable[[str, str], Path],
        tokens_to_observe: int,
    ) -> None:
        self._memory_service = memory_service
        self._token_counter = token_counter
        self._session_factory = session_factory
        self._event_bus = event_bus
        self._lock_service = lock_service
        self._memory_path_resolver = memory_path_resolver
        self._tokens_to_observe = tokens_to_observe

    async def execute(
        self,
        *,
        session_id: str,
        agent_run_id: str,
        force: bool,
    ) -> ObserveOutcome:
        sa_session = self._session_factory()
        try:
            outcome = await self._execute_with_session(
                sa_session=sa_session,
                session_id=session_id,
                agent_run_id=agent_run_id,
                force=force,
            )
            sa_session.commit()
            return outcome
        except Exception:
            sa_session.rollback()
            raise
        finally:
            sa_session.close()

    async def _execute_with_session(
        self,
        *,
        sa_session: DbSession,
        session_id: str,
        agent_run_id: str,
        force: bool,
    ) -> ObserveOutcome:
        session_repository = SessionRepository(sa_session)
        item_repository = ItemRepository(sa_session)
        agent_repository = AgentRepository(sa_session)

        # The observer runs in its OWN DB session, separate from the runner's. A full chat run
        # (root agent + every delegated sub-agent) executes inside a single transaction that
        # commits only when the run finishes (see ChatService.process_chat). turn.completed fires
        # mid-run, so a freshly-created sub-agent (delegation) is not yet visible to this separate
        # session and get() returns None. That is expected, not an error — skip quietly. Root
        # agents persist across requests, so they remain observable on their next turn.
        session = session_repository.get(session_id)
        if session is None:
            logger.debug("Observation skipped: session not yet visible session=%s", session_id)
            return ObserveOutcome(result=None, status="skipped")
        agent = agent_repository.get(agent_run_id)
        if agent is None:
            logger.debug(
                "Observation skipped: agent not yet visible (likely a delegated sub-agent created "
                "in the still-open run transaction) agent=%s session=%s",
                agent_run_id,
                session_id,
            )
            return ObserveOutcome(result=None, status="skipped")
        if not agent.agent_name:
            raise ValueError(f"Agent {agent_run_id} has no agent_name; observation not supported.")

        is_root_agent = agent.id == session.root_agent_id
        ctx = build_event_context(agent, agent.trace_id or "")
        lock = await self._lock_service.get(session.user_id, agent.agent_name)

        if lock.locked() and not force:
            self._event_bus.emit(
                ObservationFailureEvent(
                    ctx=ctx,
                    agent_name=agent.agent_name,
                    reason="locked",
                )
            )
            return ObserveOutcome(result=None, status="locked")

        async with lock:
            cursor_item_id = session.last_observed_item_id if is_root_agent else None
            unobserved = self._collect_unobserved(
                item_repository=item_repository,
                agent_run_id=agent_run_id,
                cursor_item_id=cursor_item_id,
            )

            if not unobserved:
                return ObserveOutcome(result=None, status="no_unobserved")

            token_count = self._token_counter.count_items(unobserved)
            if not force and token_count < self._tokens_to_observe:
                return ObserveOutcome(
                    result=None,
                    status="below_threshold",
                    detail=f"{token_count} < {self._tokens_to_observe}",
                )

            self._event_bus.emit(
                ObservationStartedEvent(
                    ctx=ctx,
                    agent_name=agent.agent_name,
                    message_count=len(unobserved),
                    token_count=token_count,
                )
            )
            memory_path = self._memory_path_resolver(session.user_id, agent.agent_name)
            try:
                existing = _read_memory(memory_path)
                result = await self._memory_service.observe(
                    existing_observations=existing,
                    items=unobserved,
                )
                _append_memory(memory_path, existing=existing, new_block=result.observations)
                if is_root_agent:
                    self._update_session_cursor(
                        session_repository=session_repository,
                        session=session,
                        last_item_id=unobserved[-1].id,
                        result=result,
                    )
            except Exception as exc:
                logger.exception("Observation failed for agent %s", agent_run_id)
                self._event_bus.emit(
                    ObservationFailureEvent(
                        ctx=ctx,
                        agent_name=agent.agent_name,
                        reason="error",
                        detail=str(exc),
                    )
                )
                sa_session.rollback()
                return ObserveOutcome(result=None, status="error", detail=str(exc))

            preview = result.observations[:_PREVIEW_LIMIT]
            self._event_bus.emit(
                ObservationSuccessEvent(
                    ctx=ctx,
                    agent_name=agent.agent_name,
                    new_observations_preview=preview,
                    token_count=token_count,
                )
            )
        return ObserveOutcome(result=result, status="success")

    @staticmethod
    def _collect_unobserved(
        *,
        item_repository: ItemRepository,
        agent_run_id: str,
        cursor_item_id: str | None,
    ) -> list[Item]:
        items = item_repository.list_by_agent(agent_run_id)
        if cursor_item_id is None:
            return items

        cursor_index = next((i for i, item in enumerate(items) if item.id == cursor_item_id), None)
        if cursor_index is None:
            return items
        return items[cursor_index + 1 :]

    @staticmethod
    def _update_session_cursor(
        *,
        session_repository: SessionRepository,
        session: Session,
        last_item_id: str,
        result: ObservationResult,
    ) -> None:
        session.last_observed_item_id = last_item_id
        if result.current_task is not None:
            session.current_task = result.current_task
        session.updated_at = utcnow()
        session_repository.save(session)


def _read_memory(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _append_memory(path: Path, *, existing: str | None, new_block: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_content = (existing.rstrip() + "\n\n" if existing else "") + new_block.strip() + "\n"
    path.write_text(new_content, encoding="utf-8")
