import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.chat.schema import ChatRequest, MessageInputItem
from app.config import Settings
from app.db.base import Base, utcnow
from app.db.models import AgentModel, ItemModel, SessionModel, UserModel
from app.domain import Agent, AgentConfig, AgentStatus, Item, ItemType, WaitingForEntry
from app.domain.repositories import AgentRepository, ItemRepository, SessionRepository, UserRepository
from app.events import EventBus
from app.providers import ProviderFunctionCallOutputItem, ProviderRegistry, ProviderResponse, ProviderUsage
from app.runtime.cancellation import ActiveRunRegistry
from app.runtime.runner import Runner
from app.services.agent_loader import LoadedAgent
from app.services.chat_service import ChatService
from app.tools.definitions.ask_user import ask_user_tool
from app.tools.definitions.delegate import delegate_tool
from app.tools.registry import ToolRegistry


class FakeProvider:
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = responses

    async def generate(self, request_data):  # noqa: ANN001
        del request_data
        if not self._responses:
            raise RuntimeError("No fake response left.")
        return self._responses.pop(0)

    async def stream(self, request_data):  # noqa: ANN001
        del request_data
        raise AssertionError("Streaming is not used in this test.")


class FakeMcpManager:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def parse_name(self, prefixed_name: str) -> tuple[str, str] | None:
        del prefixed_name
        return None


class FakeAgentLoader:
    def __init__(self, *, root_agent: LoadedAgent, child_agents: dict[str, LoadedAgent] | None = None) -> None:
        self._root_agent = root_agent
        self._child_agents = child_agents or {}

    def load_agent(self, agent_path):  # noqa: ANN001
        del agent_path
        return self._root_agent

    def load_agent_by_name(self, agent_name: str) -> LoadedAgent:
        agent = self._child_agents.get(agent_name)
        if agent is None:
            raise FileNotFoundError(f"Agent not found: {agent_name}")
        return agent


class StubAgentRepository:
    def get(self, agent_id: str) -> Agent | None:
        del agent_id
        return None


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


def test_build_response_output_deserializes_tool_success_result() -> None:
    created_at = utcnow()
    items = [
        Item(
            id="item-1",
            session_id="session-1",
            agent_id="agent-1",
            sequence=1,
            type=ItemType.FUNCTION_CALL_OUTPUT,
            role=None,
            content=None,
            call_id="call-1",
            name="calculator",
            arguments_json=None,
            output=json.dumps({"ok": True, "output": "15538.0"}),
            is_error=False,
            created_at=created_at,
        )
    ]

    output = ChatService._build_response_output(items, include_tool_result=True)

    assert len(output) == 1
    assert output[0].type == "function_call_output"
    assert output[0].output == "15538.0"
    assert output[0].is_error is False
    assert output[0].agent_id == "agent-1"
    assert output[0].created_at == created_at


def test_build_response_output_deserializes_tool_error_result() -> None:
    items = [
        Item(
            id="item-1",
            session_id="session-1",
            agent_id="agent-1",
            sequence=1,
            type=ItemType.FUNCTION_CALL_OUTPUT,
            role=None,
            content=None,
            call_id="call-1",
            name="calculator",
            arguments_json=None,
            output=json.dumps({"ok": False, "error": "calculator failed"}),
            is_error=True,
            created_at=utcnow(),
        )
    ]

    output = ChatService._build_response_output(items, include_tool_result=True)

    assert len(output) == 1
    assert output[0].type == "function_call_output"
    assert output[0].output == "calculator failed"
    assert output[0].is_error is True


def test_append_waiting_tool_results_exposes_waiting_question() -> None:
    now = utcnow()
    agent = Agent(
        id="agent-1",
        session_id="session-1",
        trace_id="trace-1",
        root_agent_id="agent-1",
        parent_id=None,
        source_call_id=None,
        depth=0,
        agent_name="manfred",
        status=AgentStatus.WAITING,
        turn_count=1,
        waiting_for=[
            WaitingForEntry(
                call_id="call-1",
                type="human",
                name="ask_user",
                description="Jakiego zamku szukasz?",
                agent_id="agent-1",
            )
        ],
        config=AgentConfig(
            model="openrouter:test-model",
            task="Test task",
            tools=[],
            temperature=None,
        ),
        created_at=now,
        updated_at=now,
    )
    chat_service = object.__new__(ChatService)
    chat_service.agent_repository = StubAgentRepository()

    output = chat_service._append_waiting_tool_results(agent, [], include_tool_result=True)

    assert len(output) == 1
    assert output[0].type == "function_call_output"
    assert output[0].call_id == "call-1"
    assert output[0].output == "Jakiego zamku szukasz?"
    assert output[0].agent_id == "agent-1"


@pytest.mark.asyncio
async def test_process_chat_include_tool_result_returns_session_trace_for_delegation(db_session: Session) -> None:
    user_repository = UserRepository(db_session)
    session_repository = SessionRepository(db_session)
    agent_repository = AgentRepository(db_session)
    item_repository = ItemRepository(db_session)
    tool_registry = ToolRegistry(tools=[delegate_tool, ask_user_tool])
    agent_loader = FakeAgentLoader(
        root_agent=LoadedAgent(
            agent_name="manfred",
            model="openrouter:test-model",
            tools=[delegate_tool.definition],
            system_prompt="Pomagaj uzytkownikowi.",
        ),
        child_agents={
            "research": LoadedAgent(
                agent_name="research",
                model="openrouter:test-model",
                tools=[ask_user_tool.definition],
                system_prompt="Dopytaj o brakujace szczegoly.",
            )
        },
    )
    runner = Runner(
        agent_repository=agent_repository,
        session_repository=session_repository,
        item_repository=item_repository,
        tool_registry=tool_registry,
        mcp_manager=FakeMcpManager(),
        provider_registry=ProviderRegistry(
            {
                "openrouter": FakeProvider(
                    responses=[
                        ProviderResponse(
                            output=[
                                ProviderFunctionCallOutputItem(
                                    call_id="call-parent",
                                    name="delegate",
                                    arguments={
                                        "agent_name": "research",
                                        "task": "Czy skonczyles zbierac informacje o zamku?",
                                    },
                                )
                            ],
                            usage=ProviderUsage(input_tokens=12, output_tokens=4, total_tokens=16),
                        ),
                        ProviderResponse(
                            output=[
                                ProviderFunctionCallOutputItem(
                                    call_id="call-child",
                                    name="ask_user",
                                    arguments={"question": "O jaki zamek chodzi?"},
                                )
                            ],
                            usage=ProviderUsage(input_tokens=8, output_tokens=3, total_tokens=11),
                        ),
                    ]
                )
            }
        ),
        event_bus=EventBus(),
        agent_loader=agent_loader,
        max_delegation_depth=8,
    )
    chat_service = ChatService(
        session=db_session,
        settings=Settings(
            _env_file=None,
            DEFAULT_AGENT="ignored",
            OPEN_ROUTER_LLM_MODEL="test-model",
            DEFAULT_USER_ID="default-user",
            DEFAULT_USER_NAME="Default User",
            LANGFUSE_ENABLED=False,
        ),
        agent_loader=agent_loader,
        user_repository=user_repository,
        session_repository=session_repository,
        agent_repository=agent_repository,
        item_repository=item_repository,
        runner=runner,
        active_run_registry=ActiveRunRegistry(),
    )

    response = await chat_service.process_chat(
        ChatRequest(
            input=[MessageInputItem(role="user", content="Zapytaj researchera o zamek")],
            include_tool_result=True,
        )
    )

    assert response.status == "waiting"
    assert response.waiting_for[0].type == "agent"
    child_agent_id = response.waiting_for[0].agent_id
    assert child_agent_id is not None
    assert [(item.type, item.name, item.agent_id) for item in response.output] == [
        ("function_call", "delegate", response.agent_id),
        ("function_call", "ask_user", child_agent_id),
        ("function_call_output", "ask_user", child_agent_id),
        ("function_call_output", "delegate", response.agent_id),
    ]
    assert response.output[2].output == "O jaki zamek chodzi?"
    assert response.output[3].output == "O jaki zamek chodzi?"
    assert response.output[0].created_at is not None
    assert response.output[1].created_at is not None
    assert response.output[2].created_at is None
