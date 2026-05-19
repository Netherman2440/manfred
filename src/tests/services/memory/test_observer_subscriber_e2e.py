"""End-to-end test: TurnCompletedEvent -> observer -> memory.md + cursor.

Verifies the fire-and-forget pipeline survives task GC (BackgroundTaskRegistry
holds strong refs) and that the memory.md path matches what the agent FS tools
would see (workspace_key includes user_name when present).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base, utcnow
from app.domain import (
    Agent,
    AgentConfig,
    AgentStatus,
    Item,
    ItemType,
    MessageRole,
    Session,
    SessionStatus,
    User,
)
from app.domain.repositories import (
    AgentRepository,
    ItemRepository,
    SessionRepository,
    UserRepository,
)
from app.events import EventBus, TurnCompletedEvent, build_event_context
from app.events.subscribers import ObserverSubscriber
from app.providers.types import (
    ProviderRequest,
    ProviderResponse,
    ProviderTextOutputItem,
    ProviderUsage,
)
from app.runtime.background_tasks import BackgroundTaskRegistry
from app.services.lock_service import LockService
from app.services.memory.observe_use_case import ObserveUseCase
from app.services.memory.service import MemoryService
from app.services.memory.token_counter import MemoryTokenCounter
from app.services.tiktokenizer import TiktokenizerService
from app.services.workspace_layout import WorkspaceLayoutService


class _FakeProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        return ProviderResponse(
            output=[
                ProviderTextOutputItem(
                    text=(
                        "<observations>\n* 🔴 (14:30) User loves dinosaurs\n</observations>\n"
                        "<current-task>Drawing</current-task>\n"
                    )
                )
            ],
            usage=ProviderUsage(),
        )

    async def stream(self, request: ProviderRequest):  # pragma: no cover - unused
        raise NotImplementedError


def _seed(factory: sessionmaker, *, fs_root: Path) -> tuple[str, str, str, str]:
    user_id = "u-123"
    user_name = "Bob Builder"
    session_id = uuid4().hex
    agent_id = "agent-" + session_id
    db = factory()
    now = utcnow()
    try:
        UserRepository(db).save(User(id=user_id, name=user_name, api_key_hash=None, created_at=now))
        SessionRepository(db).save(
            Session(
                id=session_id,
                user_id=user_id,
                root_agent_id=agent_id,
                status=SessionStatus.ACTIVE,
                title="t",
                created_at=now,
                updated_at=now,
            )
        )
        AgentRepository(db).save(
            Agent(
                id=agent_id,
                session_id=session_id,
                trace_id="trace-1",
                root_agent_id=agent_id,
                parent_id=None,
                source_call_id=None,
                depth=0,
                agent_name="manfred",
                status=AgentStatus.RUNNING,
                turn_count=1,
                waiting_for=[],
                config=AgentConfig(model="x", task="t", tools=[], temperature=None),
                created_at=now,
                updated_at=now,
            )
        )
        ItemRepository(db).save(
            Item(
                id="msg-user-1",
                session_id=session_id,
                agent_id=agent_id,
                sequence=1,
                type=ItemType.MESSAGE,
                role=MessageRole.USER,
                content="Tell me about dinosaurs",
                call_id=None,
                name=None,
                arguments_json=None,
                output=None,
                is_error=False,
                created_at=datetime(2026, 5, 15, 14, 30, tzinfo=UTC),
            )
        )
        ItemRepository(db).save(
            Item(
                id="msg-assistant-1",
                session_id=session_id,
                agent_id=agent_id,
                sequence=2,
                type=ItemType.MESSAGE,
                role=MessageRole.ASSISTANT,
                content="Dinosaurs are ancient reptiles",
                call_id=None,
                name=None,
                arguments_json=None,
                output=None,
                is_error=False,
                created_at=datetime(2026, 5, 15, 14, 31, tzinfo=UTC),
            )
        )
        db.commit()
    finally:
        db.close()
    return user_id, user_name, session_id, agent_id


@pytest.mark.asyncio
async def test_turn_completed_triggers_observation_and_writes_memory_with_correct_path(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    fs_root = tmp_path / ".agent_data"
    fs_root.mkdir()
    user_id, user_name, session_id, agent_id = _seed(factory, fs_root=fs_root)

    workspace_layout = WorkspaceLayoutService(
        repo_root=tmp_path,
        workspace_path=".agent_data",
        agent_mount_names=["agents"],
    )
    expected_layout = workspace_layout.resolve_user_workspace(user_id=user_id, user_name=user_name)
    expected_memory_path = expected_layout.root / "agents" / "manfred" / "memory.md"

    def memory_path_resolver(uid: str, agent_name: str) -> Path:
        # Mirror container's resolver: look up the user so workspace_key uses name+id.
        sa = factory()
        try:
            user = UserRepository(sa).get(uid)
        finally:
            sa.close()
        layout = workspace_layout.resolve_user_workspace(user_id=uid, user_name=user.name if user else None)
        return layout.root / "agents" / agent_name / "memory.md"

    settings = Settings(
        _env_file=None,
        OBSERVATIONAL_MEMORY_ENABLED=True,
        TOKENS_TO_OBSERVE=1,  # force observation regardless of message length
    )
    event_bus = EventBus()
    provider = _FakeProvider()
    memory_service = MemoryService(provider=provider, model="x")
    token_counter = MemoryTokenCounter(TiktokenizerService())
    lock_service = LockService()
    background_registry = BackgroundTaskRegistry()
    observe_use_case = ObserveUseCase(
        memory_service=memory_service,
        token_counter=token_counter,
        session_factory=factory,
        event_bus=event_bus,
        lock_service=lock_service,
        memory_path_resolver=memory_path_resolver,
        tokens_to_observe=settings.TOKENS_TO_OBSERVE,
    )
    subscriber = ObserverSubscriber(
        settings=settings,
        observe_use_case=observe_use_case,
        background_task_registry=background_registry,
    )
    subscriber.subscribe(event_bus)

    db = factory()
    try:
        agent = AgentRepository(db).get(agent_id)
        assert agent is not None
    finally:
        db.close()

    event_bus.emit(
        TurnCompletedEvent(
            ctx=build_event_context(agent, trace_id="trace-1"),
            turn_count=1,
            usage=None,
        )
    )

    # Wait for the background task to finish.
    for _ in range(50):
        await asyncio.sleep(0.05)
        if expected_memory_path.exists() and provider.calls >= 1:
            break

    assert provider.calls == 1
    assert expected_memory_path.exists(), f"memory.md not at expected path: {expected_memory_path}"
    content = expected_memory_path.read_text(encoding="utf-8")
    assert "User loves dinosaurs" in content

    db = factory()
    try:
        session = SessionRepository(db).get(session_id)
        assert session is not None
        assert session.last_observed_item_id == "msg-assistant-1"
        assert session.current_task == "Drawing"
    finally:
        db.close()

    Base.metadata.drop_all(engine)
    engine.dispose()
