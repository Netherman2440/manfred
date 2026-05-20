from collections.abc import Iterator

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base, utcnow
from app.domain import (
    Agent,
    AgentConfig,
    AgentStatus,
    Session,
    SessionStatus,
    User,
)
from app.domain.repositories import AgentRepository, SessionRepository, UserRepository
from app.main import container, create_app


class StubMcpManager:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _seed_session(test_session_factory: sessionmaker, *, session_id: str, user_id: str) -> None:
    db = test_session_factory()
    now = utcnow()
    try:
        if UserRepository(db).get(user_id) is None:
            UserRepository(db).save(User(id=user_id, name=f"{user_id}-name", api_key_hash=None, created_at=now))
        SessionRepository(db).save(
            Session(
                id=session_id,
                user_id=user_id,
                root_agent_id="agent-" + session_id,
                status=SessionStatus.ACTIVE,
                title=f"title-{session_id}",
                created_at=now,
                updated_at=now,
            )
        )
        AgentRepository(db).save(
            Agent(
                id="agent-" + session_id,
                session_id=session_id,
                trace_id="trace-" + session_id,
                root_agent_id="agent-" + session_id,
                parent_id=None,
                source_call_id=None,
                depth=0,
                agent_name="manfred",
                status=AgentStatus.COMPLETED,
                turn_count=1,
                waiting_for=[],
                config=AgentConfig(model="x", task="t", tools=[], temperature=None),
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    finally:
        db.close()


def _make_client(*, observational_memory_enabled: bool) -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        DATABASE_URL="sqlite://",
        LANGFUSE_ENABLED=False,
        OBSERVATIONAL_MEMORY_ENABLED=observational_memory_enabled,
    )

    container.settings.override(providers.Object(settings))
    container.db_engine.override(providers.Object(engine))
    container.session_factory.override(providers.Object(factory))
    container.mcp_manager.override(providers.Object(StubMcpManager()))
    container.langfuse_subscriber.override(providers.Object(None))

    app = create_app()
    client = TestClient(app)
    client.__enter__()
    return client, factory


def _reset_overrides() -> None:
    container.langfuse_subscriber.reset_override()
    container.mcp_manager.reset_override()
    container.session_factory.reset_override()
    container.db_engine.reset_override()
    container.settings.reset_override()
    container.reset_singletons()


@pytest.fixture
def client_with_flag_off() -> Iterator[tuple[TestClient, sessionmaker]]:
    client, factory = _make_client(observational_memory_enabled=False)
    try:
        yield client, factory
    finally:
        try:
            client.__exit__(None, None, None)
        finally:
            _reset_overrides()


@pytest.fixture
def client_with_flag_on() -> Iterator[tuple[TestClient, sessionmaker]]:
    client, factory = _make_client(observational_memory_enabled=True)
    try:
        yield client, factory
    finally:
        try:
            client.__exit__(None, None, None)
        finally:
            _reset_overrides()


def test_summarize_returns_503_when_flag_disabled(
    client_with_flag_off: tuple[TestClient, sessionmaker],
) -> None:
    client, factory = client_with_flag_off
    _seed_session(factory, session_id="session-1", user_id="default-user")

    response = client.post("/api/v1/chat/sessions/session-1/summarize")

    assert response.status_code == 503


def test_summarize_returns_404_for_unknown_session_when_flag_on(
    client_with_flag_on: tuple[TestClient, sessionmaker],
) -> None:
    client, _ = client_with_flag_on

    response = client.post("/api/v1/chat/sessions/missing/summarize")

    assert response.status_code == 404


def test_summarize_returns_204_for_session_without_unobserved_items(
    client_with_flag_on: tuple[TestClient, sessionmaker],
) -> None:
    client, factory = client_with_flag_on
    _seed_session(factory, session_id="session-empty", user_id="default-user")

    response = client.post("/api/v1/chat/sessions/session-empty/summarize")

    assert response.status_code == 204
