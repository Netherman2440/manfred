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
from app.mcp import McpToolInfo
from app.providers import (
    Provider,
    ProviderDoneEvent,
    ProviderFunctionCallDeltaEvent,
    ProviderFunctionCallDoneEvent,
    ProviderFunctionCallOutputItem,
    ProviderRegistry,
    ProviderResponse,
    ProviderStreamEvent,
    ProviderTextDeltaEvent,
    ProviderTextDoneEvent,
    ProviderTextOutputItem,
    ProviderUsage,
)
from app.runtime.runner import Runner
from app.tools.registry import ToolRegistry


class FakeProvider(Provider):
    def __init__(
        self,
        responses: list[ProviderResponse],
        stream_events: list[list[ProviderStreamEvent]] | None = None,
    ) -> None:
        self._responses = responses
        self._stream_events = stream_events or []

    async def generate(self, request_data):  # noqa: ANN001
        if not self._responses:
            raise RuntimeError("No fake response left.")
        return self._responses.pop(0)

    async def stream(self, request_data):  # noqa: ANN001
        del request_data
        if self._stream_events:
            for event in self._stream_events.pop(0):
                yield event
            return

        if not self._responses:
            raise RuntimeError("No fake response left.")

        response = self._responses.pop(0)
        yield ProviderDoneEvent(response=response)


class FakeMcpManager:
    def __init__(
        self,
        *,
        tools: list[McpToolInfo] | None = None,
        results: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
    ) -> None:
        self._tools = {tool.prefixed_name: tool for tool in tools or []}
        self._results = results or {}
        self._errors = errors or {}

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def servers(self) -> list[str]:
        return sorted({tool.server for tool in self._tools.values()})

    def server_status(self, name: str) -> str:
        return "connected" if name in self.servers() else "disconnected"

    def parse_name(self, prefixed_name: str) -> tuple[str, str] | None:
        if "__" not in prefixed_name:
            return None
        server_name, tool_name = prefixed_name.split("__", 1)
        if not server_name or not tool_name:
            return None
        return server_name, tool_name

    def list_tools(self) -> list[McpToolInfo]:
        return list(self._tools.values())

    def list_server_tools(self, server_name: str) -> list[McpToolInfo]:
        return [tool for tool in self._tools.values() if tool.server == server_name]

    def get_tool(self, prefixed_name: str) -> McpToolInfo | None:
        return self._tools.get(prefixed_name)

    async def call_tool(
        self,
        prefixed_name: str,
        arguments: dict[str, object],
        signal: object | None = None,
    ) -> str:
        del arguments
        del signal
        if prefixed_name in self._errors:
            raise RuntimeError(self._errors[prefixed_name])
        return self._results[prefixed_name]


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
    provider_streams: list[list[ProviderStreamEvent]] | None = None,
    tools: list[Tool],
    mcp_manager: FakeMcpManager | None = None,
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
            agent_name="manfred",
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
        mcp_manager=mcp_manager or FakeMcpManager(),
        provider_registry=ProviderRegistry(
            {
                "openrouter": FakeProvider(
                    list(provider_responses),
                    stream_events=list(provider_streams or []),
                )
            }
        ),
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


@pytest.mark.asyncio
async def test_runner_executes_mcp_tool_and_continues(db_session: Session) -> None:
    mcp_tool = McpToolInfo(
        server="files",
        original_name="fs_read",
        prefixed_name="files__fs_read",
        description="Read a file",
        input_schema={"type": "object"},
    )
    runner, agent_id, event_types = make_runner(
        db_session,
        provider_responses=[
            ProviderResponse(
                output=[
                    ProviderFunctionCallOutputItem(
                        call_id="call-1",
                        name="files__fs_read",
                        arguments={"path": "docs/spec.md"},
                    )
                ],
                usage=ProviderUsage(input_tokens=8, output_tokens=3, total_tokens=11),
            ),
            ProviderResponse(
                output=[ProviderTextOutputItem(text="Recovered answer")],
                usage=ProviderUsage(input_tokens=6, output_tokens=4, total_tokens=10),
            ),
        ],
        tools=[],
        mcp_manager=FakeMcpManager(
            tools=[mcp_tool],
            results={"files__fs_read": "file contents"},
        ),
    )

    result = await runner.run_agent(agent_id, last_agent_sequence=0)
    stored_items = ItemRepository(db_session).list_by_agent(agent_id)

    assert result.ok is True
    assert stored_items[2].type == ItemType.FUNCTION_CALL_OUTPUT
    assert stored_items[2].is_error is False
    assert stored_items[2].output == '{"ok": true, "output": "file contents"}'
    assert event_types == [
        "agent.started",
        "turn.started",
        "generation.completed",
        "tool.called",
        "tool.completed",
        "turn.completed",
        "turn.started",
        "generation.completed",
        "turn.completed",
        "agent.completed",
    ]


@pytest.mark.asyncio
async def test_runner_marks_mcp_tool_failure_and_continues(db_session: Session) -> None:
    mcp_tool = McpToolInfo(
        server="files",
        original_name="fs_read",
        prefixed_name="files__fs_read",
        description="Read a file",
        input_schema={"type": "object"},
    )
    runner, agent_id, event_types = make_runner(
        db_session,
        provider_responses=[
            ProviderResponse(
                output=[
                    ProviderFunctionCallOutputItem(
                        call_id="call-1",
                        name="files__fs_read",
                        arguments={"path": "docs/spec.md"},
                    )
                ],
                usage=ProviderUsage(input_tokens=8, output_tokens=3, total_tokens=11),
            ),
            ProviderResponse(
                output=[ProviderTextOutputItem(text="Recovered answer")],
                usage=ProviderUsage(input_tokens=6, output_tokens=4, total_tokens=10),
            ),
        ],
        tools=[],
        mcp_manager=FakeMcpManager(
            tools=[mcp_tool],
            errors={"files__fs_read": "read failed"},
        ),
    )

    result = await runner.run_agent(agent_id, last_agent_sequence=0)
    stored_items = ItemRepository(db_session).list_by_agent(agent_id)

    assert result.ok is True
    assert stored_items[2].type == ItemType.FUNCTION_CALL_OUTPUT
    assert stored_items[2].is_error is True
    assert stored_items[2].output == '{"ok": false, "error": "read failed"}'
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
async def test_runner_stream_emits_text_events_and_persists_output(db_session: Session) -> None:
    runner, agent_id, event_types = make_runner(
        db_session,
        provider_responses=[],
        provider_streams=[
            [
                ProviderTextDeltaEvent(delta="Final "),
                ProviderTextDeltaEvent(delta="answer"),
                ProviderTextDoneEvent(text="Final answer"),
                ProviderDoneEvent(
                    response=ProviderResponse(
                        output=[ProviderTextOutputItem(text="Final answer")],
                        usage=ProviderUsage(input_tokens=10, output_tokens=5, total_tokens=15),
                    )
                ),
            ]
        ],
        tools=[],
    )

    events = [event async for event in runner.run_agent_stream(agent_id, last_agent_sequence=0)]
    stored_items = ItemRepository(db_session).list_by_agent(agent_id)

    assert [event.type for event in events] == [
        "text_delta",
        "text_delta",
        "text_done",
        "done",
    ]
    assert stored_items[-1].content == "Final answer"
    assert event_types == [
        "agent.started",
        "turn.started",
        "generation.completed",
        "turn.completed",
        "agent.completed",
    ]


@pytest.mark.asyncio
async def test_runner_stream_continues_after_tool_call(db_session: Session) -> None:
    async def calculator(arguments: dict[str, object], signal: object | None) -> dict[str, object]:
        del signal
        return {"ok": True, "output": f"{arguments['value']}"}

    runner, agent_id, event_types = make_runner(
        db_session,
        provider_responses=[],
        provider_streams=[
            [
                ProviderFunctionCallDeltaEvent(
                    call_id="call-1",
                    name="calculator",
                    arguments_delta='{"value":',
                ),
                ProviderFunctionCallDeltaEvent(
                    call_id="call-1",
                    name="calculator",
                    arguments_delta=" 7}",
                ),
                ProviderFunctionCallDoneEvent(
                    call_id="call-1",
                    name="calculator",
                    arguments={"value": 7},
                ),
                ProviderDoneEvent(
                    response=ProviderResponse(
                        output=[
                            ProviderFunctionCallOutputItem(
                                call_id="call-1",
                                name="calculator",
                                arguments={"value": 7},
                            )
                        ],
                        usage=ProviderUsage(input_tokens=8, output_tokens=3, total_tokens=11),
                        finish_reason="tool_calls",
                    )
                ),
            ],
            [
                ProviderTextDeltaEvent(delta="Recovered answer"),
                ProviderTextDoneEvent(text="Recovered answer"),
                ProviderDoneEvent(
                    response=ProviderResponse(
                        output=[ProviderTextOutputItem(text="Recovered answer")],
                        usage=ProviderUsage(input_tokens=6, output_tokens=4, total_tokens=10),
                    )
                ),
            ],
        ],
        tools=[
            Tool(
                type="sync",
                definition=FunctionToolDefinition(
                    name="calculator",
                    description="Calculator",
                    parameters={"type": "object"},
                ),
                handler=calculator,
            )
        ],
    )

    events = [event async for event in runner.run_agent_stream(agent_id, last_agent_sequence=0)]
    stored_items = ItemRepository(db_session).list_by_agent(agent_id)

    assert [event.type for event in events] == [
        "function_call_delta",
        "function_call_delta",
        "function_call_done",
        "done",
        "text_delta",
        "text_done",
        "done",
    ]
    assert [item.type.value for item in stored_items[1:]] == [
        "function_call",
        "function_call_output",
        "message",
    ]
    assert stored_items[-1].content == "Recovered answer"
    assert event_types == [
        "agent.started",
        "turn.started",
        "generation.completed",
        "tool.called",
        "tool.completed",
        "turn.completed",
        "turn.started",
        "generation.completed",
        "turn.completed",
        "agent.completed",
    ]


def test_runner_uses_last_new_user_message_for_run_input() -> None:
    now = utcnow()
    agent = Agent(
        id="agent-1",
        session_id="session-1",
        root_agent_id="agent-1",
        parent_id=None,
        depth=0,
        agent_name="manfred",
        status=AgentStatus.PENDING,
        turn_count=0,
        config=AgentConfig(
            model="openrouter:test-model",
            task="Solve the task",
            tools=[],
            temperature=None,
        ),
        created_at=now,
        updated_at=now,
    )
    session = DomainSession(
        id="session-1",
        user_id="user-1",
        root_agent_id="agent-1",
        status=SessionStatus.ACTIVE,
        title=None,
        created_at=now,
        updated_at=now,
    )
    items = [
        Item(
            id=uuid4().hex,
            session_id="session-1",
            agent_id="agent-1",
            sequence=1,
            type=ItemType.MESSAGE,
            role=MessageRole.USER,
            content="Poprzednia wiadomosc",
            call_id=None,
            name=None,
            arguments_json=None,
            output=None,
            is_error=False,
            created_at=now,
        ),
        Item(
            id=uuid4().hex,
            session_id="session-1",
            agent_id="agent-1",
            sequence=2,
            type=ItemType.MESSAGE,
            role=MessageRole.USER,
            content="Pierwsza nowa wiadomosc",
            call_id=None,
            name=None,
            arguments_json=None,
            output=None,
            is_error=False,
            created_at=now,
        ),
        Item(
            id=uuid4().hex,
            session_id="session-1",
            agent_id="agent-1",
            sequence=3,
            type=ItemType.MESSAGE,
            role=MessageRole.USER,
            content="Ostatnia nowa wiadomosc",
            call_id=None,
            name=None,
            arguments_json=None,
            output=None,
            is_error=False,
            created_at=now,
        ),
    ]
    context = type(
        "Context",
        (),
        {
            "agent": agent,
            "session": session,
            "items": items,
            "trace_id": "trace-1",
            "last_agent_sequence": 1,
        },
    )()

    assert Runner._find_run_user_input(context) == "Ostatnia nowa wiadomosc"
