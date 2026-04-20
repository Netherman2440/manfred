import json
import re
from collections.abc import Iterator
from datetime import timedelta

import pytest
from dependency_injector import providers
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.cors import LOCALHOST_CORS_ORIGIN_REGEX
from app.config import Settings
from app.db.base import Base, utcnow
from app.domain import (
    Agent,
    AgentConfig,
    AgentStatus,
    FunctionToolDefinition,
    Item,
    ItemType,
    MessageRole,
    Session,
    SessionStatus,
    User,
    WaitingForEntry,
)
from app.domain.repositories import AgentRepository, ItemRepository, SessionRepository, UserRepository
from app.main import container, create_app


class StubMcpManager:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.fixture
def api_client() -> Iterator[tuple[TestClient, sessionmaker]]:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    settings = Settings(
        _env_file=None,
        DATABASE_URL="sqlite://",
        API_CORS_ORIGINS="http://localhost:3001",
        API_CORS_ALLOW_LOCALHOST=True,
        LANGFUSE_ENABLED=False,
    )

    container.settings.override(providers.Object(settings))
    container.db_engine.override(providers.Object(engine))
    container.session_factory.override(providers.Object(test_session_factory))
    container.mcp_manager.override(providers.Object(StubMcpManager()))
    container.langfuse_subscriber.override(providers.Object(None))

    app = create_app()

    try:
        with TestClient(app) as client:
            yield client, test_session_factory
    finally:
        container.langfuse_subscriber.reset_override()
        container.mcp_manager.reset_override()
        container.session_factory.reset_override()
        container.db_engine.reset_override()
        container.settings.reset_override()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_session_graph(
    test_session_factory: sessionmaker,
    *,
    session_id: str,
    user_id: str,
    updated_at_offset_seconds: int = 0,
    waiting_for: list[WaitingForEntry] | None = None,
) -> None:
    db = test_session_factory()
    now = utcnow()
    try:
        user_repository = UserRepository(db)
        session_repository = SessionRepository(db)
        agent_repository = AgentRepository(db)

        if user_repository.get(user_id) is None:
            user_repository.save(
                User(
                    id=user_id,
                    name=f"{user_id}-name",
                    api_key_hash=None,
                    created_at=now,
                )
            )

        session_repository.save(
            Session(
                id=session_id,
                user_id=user_id,
                root_agent_id="agent-" + session_id,
                status=SessionStatus.ACTIVE,
                title=f"title-{session_id}",
                created_at=now,
                updated_at=now - timedelta(seconds=updated_at_offset_seconds),
            )
        )
        agent_repository.save(
            Agent(
                id="agent-" + session_id,
                session_id=session_id,
                trace_id="trace-" + session_id,
                root_agent_id="agent-" + session_id,
                parent_id=None,
                source_call_id=None,
                depth=0,
                agent_name="Manfred",
                status=AgentStatus.WAITING if waiting_for else AgentStatus.COMPLETED,
                turn_count=1,
                waiting_for=waiting_for or [],
                config=AgentConfig(
                    model="openrouter:test-model",
                    task="Test task",
                    tools=[FunctionToolDefinition(name="calculator", description="math", parameters={})],
                    temperature=None,
                ),
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    finally:
        db.close()


def _seed_session_items(test_session_factory: sessionmaker, *, session_id: str) -> None:
    db = test_session_factory()
    now = utcnow()
    try:
        item_repository = ItemRepository(db)
        item_repository.save(
            Item(
                id="item-message-user",
                session_id=session_id,
                agent_id="agent-" + session_id,
                sequence=1,
                type=ItemType.MESSAGE,
                role=MessageRole.USER,
                content="Potrzebuję planu wdrożenia.",
                call_id=None,
                name=None,
                arguments_json=None,
                output=None,
                is_error=False,
                created_at=now,
            )
        )
        item_repository.save(
            Item(
                id="item-function-call",
                session_id=session_id,
                agent_id="agent-" + session_id,
                sequence=2,
                type=ItemType.FUNCTION_CALL,
                role=MessageRole.ASSISTANT,
                content=None,
                call_id="call-1",
                name="search_docs",
                arguments_json=json.dumps({"query": "sessions api", "limit": 3}),
                output=None,
                is_error=False,
                created_at=now,
            )
        )
        item_repository.save(
            Item(
                id="item-function-output",
                session_id=session_id,
                agent_id="agent-" + session_id,
                sequence=3,
                type=ItemType.FUNCTION_CALL_OUTPUT,
                role=MessageRole.ASSISTANT,
                content=None,
                call_id="call-1",
                name="search_docs",
                arguments_json=None,
                output=json.dumps({"ok": True, "output": {"hits": 3}}),
                is_error=False,
                created_at=now,
            )
        )
        item_repository.save(
            Item(
                id="item-message-assistant",
                session_id=session_id,
                agent_id="agent-" + session_id,
                sequence=4,
                type=ItemType.MESSAGE,
                role=MessageRole.ASSISTANT,
                content="Mam już szkic integracji.",
                call_id=None,
                name=None,
                arguments_json=None,
                output=None,
                is_error=False,
                created_at=now,
            )
        )
        db.commit()
    finally:
        db.close()


def test_list_user_sessions_returns_items_sorted_by_updated_at_desc(
    api_client: tuple[TestClient, sessionmaker],
) -> None:
    client, test_session_factory = api_client
    _seed_session_graph(test_session_factory, session_id="session-new", user_id="default-user", updated_at_offset_seconds=0)
    _seed_session_items(test_session_factory, session_id="session-new")
    _seed_session_graph(test_session_factory, session_id="session-old", user_id="default-user", updated_at_offset_seconds=5)

    response = client.get("/api/v1/users/default-user/sessions")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["data"]] == ["session-new", "session-old"]
    assert payload["data"][0]["root_agent_status"] == "completed"
    assert payload["data"][0]["waiting_for_count"] == 0
    assert payload["data"][0]["last_message_preview"] == "Mam już szkic integracji."


def test_list_user_sessions_returns_empty_data_for_user_without_sessions(
    api_client: tuple[TestClient, sessionmaker],
) -> None:
    client, _ = api_client

    response = client.get("/api/v1/users/default-user/sessions")

    assert response.status_code == 200
    assert response.json() == {"data": []}


def test_get_user_session_detail_returns_transcript_items(
    api_client: tuple[TestClient, sessionmaker],
) -> None:
    client, test_session_factory = api_client
    _seed_session_graph(
        test_session_factory,
        session_id="session-1",
        user_id="default-user",
        waiting_for=[
            WaitingForEntry(
                call_id="call-human",
                type="human",
                name="ask_user",
                description="Doprecyzuj zakres.",
                agent_id="agent-session-1",
            )
        ],
    )
    _seed_session_items(test_session_factory, session_id="session-1")

    response = client.get("/api/v1/users/default-user/sessions/session-1")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["session"]["id"] == "session-1"
    assert payload["root_agent"]["status"] == "waiting"
    assert payload["root_agent"]["waiting_for"][0]["call_id"] == "call-human"
    assert payload["items"][0]["id"] == "item-message-user"
    assert payload["items"][0]["sequence"] == 1
    assert payload["items"][0]["agent_id"] == "agent-session-1"
    assert payload["items"][0]["type"] == "message"
    assert payload["items"][0]["role"] == "user"
    assert payload["items"][0]["content"] == "Potrzebuję planu wdrożenia."
    assert payload["items"][0]["created_at"]
    assert payload["items"][1]["id"] == "item-function-call"
    assert payload["items"][1]["sequence"] == 2
    assert payload["items"][1]["agent_id"] == "agent-session-1"
    assert payload["items"][1]["type"] == "function_call"
    assert payload["items"][1]["call_id"] == "call-1"
    assert payload["items"][1]["name"] == "search_docs"
    assert payload["items"][1]["arguments"] == {"query": "sessions api", "limit": 3}
    assert payload["items"][1]["created_at"]
    assert payload["items"][2]["id"] == "item-function-output"
    assert payload["items"][2]["sequence"] == 3
    assert payload["items"][2]["agent_id"] == "agent-session-1"
    assert payload["items"][2]["type"] == "function_call_output"
    assert payload["items"][2]["call_id"] == "call-1"
    assert payload["items"][2]["name"] == "search_docs"
    assert payload["items"][2]["tool_result"] == {"ok": True, "output": {"hits": 3}}
    assert payload["items"][2]["is_error"] is False
    assert payload["items"][2]["created_at"]


def test_get_user_session_detail_returns_404_for_unknown_or_foreign_session(
    api_client: tuple[TestClient, sessionmaker],
) -> None:
    client, test_session_factory = api_client
    _seed_session_graph(test_session_factory, session_id="session-foreign", user_id="other-user")

    foreign_response = client.get("/api/v1/users/default-user/sessions/session-foreign")
    missing_response = client.get("/api/v1/users/default-user/sessions/missing-session")

    assert foreign_response.status_code == 404
    assert missing_response.status_code == 404


def test_create_app_configures_cors_for_dynamic_localhost_ports() -> None:
    settings = Settings(
        _env_file=None,
        API_CORS_ORIGINS="http://localhost:3001",
        API_CORS_ALLOW_LOCALHOST=True,
        LANGFUSE_ENABLED=False,
    )

    container.settings.override(providers.Object(settings))
    try:
        app = create_app()
    finally:
        container.settings.reset_override()

    cors_middleware = next(
        middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware
    )

    assert cors_middleware.kwargs["allow_origins"] == ["http://localhost:3001"]
    assert cors_middleware.kwargs["allow_origin_regex"] == LOCALHOST_CORS_ORIGIN_REGEX
    assert re.match(LOCALHOST_CORS_ORIGIN_REGEX, "http://localhost:37765")
    assert re.match(LOCALHOST_CORS_ORIGIN_REGEX, "https://127.0.0.1:8443")
    assert re.match(LOCALHOST_CORS_ORIGIN_REGEX, "https://example.com") is None
