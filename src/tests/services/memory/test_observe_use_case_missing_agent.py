"""Regression: observing an agent not yet visible to the observer's separate DB
session must skip gracefully, not raise.

A full chat run (root + delegated sub-agents) commits in ONE transaction at the
end of the run. turn.completed fires mid-run, so a freshly-created delegated
sub-agent is not yet committed and the observer's separate session cannot see it.
That previously raised ValueError("Agent not found"); it must now return status
"skipped".
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base, utcnow
from app.domain import Session, SessionStatus, User
from app.domain.repositories import SessionRepository, UserRepository
from app.events import EventBus
from app.services.lock_service import LockService
from app.services.memory.observe_use_case import ObserveUseCase
from app.services.memory.token_counter import MemoryTokenCounter
from app.services.tiktokenizer import TiktokenizerService


class _UnusedProvider:
    async def generate(self, request):  # pragma: no cover - must never be called
        raise AssertionError("memory provider must not be called when agent is missing")

    async def stream(self, request):  # pragma: no cover - unused
        raise NotImplementedError


def _make_use_case(factory: sessionmaker) -> ObserveUseCase:
    from app.services.memory.service import MemoryService

    return ObserveUseCase(
        memory_service=MemoryService(provider=_UnusedProvider(), model="x"),
        token_counter=MemoryTokenCounter(TiktokenizerService()),
        session_factory=factory,
        event_bus=EventBus(),
        lock_service=LockService(),
        memory_path_resolver=lambda uid, name: Path("/nonexistent") / name / "memory.md",
        tokens_to_observe=1,
    )


@pytest.fixture()
def factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.mark.asyncio
async def test_missing_agent_skips_without_raising(factory: sessionmaker) -> None:
    # Session exists (committed) but the agent does not — the delegation race.
    session_id = uuid4().hex
    db = factory()
    now = utcnow()
    try:
        UserRepository(db).save(User(id="u-1", name="Bob", api_key_hash=None, created_at=now))
        SessionRepository(db).save(
            Session(
                id=session_id,
                user_id="u-1",
                root_agent_id="root-agent",
                status=SessionStatus.ACTIVE,
                title="t",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    finally:
        db.close()

    outcome = await _make_use_case(factory).execute(
        session_id=session_id,
        agent_run_id="uncommitted-child-agent",
        force=True,
    )
    assert outcome.status == "skipped"
    assert outcome.result is None


@pytest.mark.asyncio
async def test_missing_session_skips_without_raising(factory: sessionmaker) -> None:
    outcome = await _make_use_case(factory).execute(
        session_id="nonexistent-session",
        agent_run_id="whatever",
        force=True,
    )
    assert outcome.status == "skipped"
    assert outcome.result is None
