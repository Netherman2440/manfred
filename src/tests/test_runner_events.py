from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, utcnow
from app.db.models import AgentModel, ItemModel, SessionModel, UserModel
from app.domain import (
    Agent,
    AgentConfig,
    AgentStatus,
    FunctionToolDefinition,
    Item,
    ItemType,
    MessageRole,
    Session as DomainSession,
    SessionStatus,
    Tool,
    User,
)
from app.domain.repositories import AgentRepository, ItemRepository, SessionRepository, UserRepository
from app.events import EventBus
from app.providers import (
    Provider,
    ProviderFunctionCallOutputItem,
    ProviderRegistry,
    ProviderResponse,
    ProviderTextOutputItem,
    ProviderUsage,
)
from app.runtime.runner import Runner
from app.tools.registry import ToolRegistry


class FakeProvider(Provider):
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = responses

    async def generate(self, request_data):  # noqa: ANN001
        if not self._responses:
            raise RuntimeError("No fake response left.")
        return self._responses.pop(0)


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            UserModel.__table__,
            SessionModel.__table__,
            AgentModel.__table__,
            ItemModel.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def make_runner(
    db_session: Session,
    *,
    provider_responses: list[ProviderResponse],
    tools: list[Tool],
    model: str = "openrouter:test-model",
) -> tuple[Runner, str, list[str]]:
    user_repository = UserRepository(db_session)
    session_repository = SessionRepository(db_session)
    agent_repository = AgentRepository(db_session)
    item_repository = ItemRepository(db_session)

    now = utcnow()
    user_repository.save(User(id="user-1", name="User", api_key_hash=None, created_at=now))
    session = session_repository.save(
        DomainSession(
            id="session-1",
            user_id="user-1",
            root_agent_id="agent-1",
            status=SessionStatus.ACTIVE,
            title=None,
            created_at=now,
            updated_at=now,
        )
    )
    agent = agent_repository.save(
        Agent(
            id="agent-1",
            session_id=session.id,
            root_agent_id="agent-1",
            parent_id=None,
            depth=0,
            status=AgentStatus.PENDING,
            turn_count=0,
            config=AgentConfig(
                model=model,
                task="Solve the task",
                tools=[tool.definition for tool in tools],
                temperature=None,
            ),
            created_at=now,
            updated_at=now,
        )
    )
    item_repository.save(
        Item(
            id=uuid4().hex,
            session_id=session.id,
            agent_id=agent.id,
            sequence=1,
            type=ItemType.MESSAGE,
            role=MessageRole.USER,
            content="User prompt",
            call_id=None,
            name=None,
            arguments_json=None,
            output=None,
            is_error=False,
            created_at=now,
        )
    )

    event_bus = EventBus()
    event_types: list[str] = []
    event_bus.subscribe("any", lambda event: event_types.append(event.type))

    runner = Runner(
        agent_repository=agent_repository,
        session_repository=session_repository,
        item_repository=item_repository,
        tool_registry=ToolRegistry(tools=tools),
        provider_registry=ProviderRegistry({"openrouter": FakeProvider(list(provider_responses))}),
        event_bus=event_bus,
    )
    return runner, agent.id, event_types


@pytest.mark.asyncio
async def test_runner_emits_happy_path_events_in_order(db_session: Session) -> None:
    runner, agent_id, event_types = make_runner(
        db_session,
        provider_responses=[
            ProviderResponse(
                output=[ProviderTextOutputItem(text="Final answer")],
                usage=ProviderUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            )
        ],
        tools=[],
    )

    result = await runner.run_agent(agent_id, last_agent_sequence=0)

    assert result.ok is True
    assert event_types == [
        "agent.started",
        "turn.started",
        "generation.completed",
        "turn.completed",
        "agent.completed",
    ]


@pytest.mark.asyncio
async def test_runner_emits_tool_failed_and_continues(db_session: Session) -> None:
    async def failing_tool(arguments: dict[str, object], signal: object | None) -> dict[str, object]:
        del signal
        return {"ok": False, "error": f"calculator failed for {arguments['value']}"}

    runner, agent_id, event_types = make_runner(
        db_session,
        provider_responses=[
            ProviderResponse(
                output=[
                    ProviderFunctionCallOutputItem(
                        call_id="call-1",
                        name="calculator",
                        arguments={"value": 7},
                    )
                ],
                usage=ProviderUsage(input_tokens=8, output_tokens=3, total_tokens=11),
            ),
            ProviderResponse(
                output=[ProviderTextOutputItem(text="Recovered answer")],
                usage=ProviderUsage(input_tokens=6, output_tokens=4, total_tokens=10),
            ),
        ],
        tools=[
            Tool(
                type="sync",
                definition=FunctionToolDefinition(
                    name="calculator",
                    description="Calculator",
                    parameters={"type": "object"},
                ),
                handler=failing_tool,
            )
        ],
    )

    result = await runner.run_agent(agent_id, last_agent_sequence=0)

    assert result.ok is True
    assert event_types == [
        "agent.started",
        "turn.started",
        "generation.completed",
        "tool.called",
        "tool.failed",
        "turn.completed",
        "turn.started",
        "generation.completed",
        "turn.completed",
        "agent.completed",
    ]


@pytest.mark.asyncio
async def test_runner_emits_agent_failed_for_unknown_provider(db_session: Session) -> None:
    runner, agent_id, event_types = make_runner(
        db_session,
        provider_responses=[],
        tools=[],
        model="missing-provider:test-model",
    )

    result = await runner.run_agent(agent_id, last_agent_sequence=0)

    assert result.ok is False
    assert event_types == [
        "agent.started",
        "turn.started",
        "agent.failed",
    ]
