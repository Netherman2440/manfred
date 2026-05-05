import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, utcnow
from app.db.models import AgentModel, ItemAttachmentModel, ItemModel, QueuedInputModel, SessionModel, UserModel
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
    ToolExecutionContext,
    User,
)
from app.domain.repositories import AgentRepository, ItemRepository, QueuedInputRepository, SessionRepository, UserRepository
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
from app.runtime.cancellation import CancellationSignal
from app.runtime.message_queue import SessionMessageQueue
from app.runtime.runner import Runner
from app.services.agent_loader import LoadedAgent
from app.tools.definitions.ask_user import ask_user_tool
from app.tools.definitions.delegate import delegate_tool
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


class FakeAgentLoader:
    def __init__(self, agents: dict[str, LoadedAgent] | None = None) -> None:
        self._agents = agents or {}

    def load_agent_by_name(self, agent_name: str) -> LoadedAgent:
        agent = self._agents.get(agent_name)
        if agent is None:
            raise FileNotFoundError(f"Agent not found: {agent_name}")
        return agent


class BlockingProvider(Provider):
    async def generate(self, request_data):  # noqa: ANN001
        signal = request_data.signal
        if signal is None:
            raise RuntimeError("Cancellation signal is required for this test.")
        await signal.wait()
        signal.raise_if_cancelled()
        raise AssertionError("Signal should cancel before continuing.")

    async def stream(self, request_data):  # noqa: ANN001
        signal = request_data.signal
        if signal is None:
            raise RuntimeError("Cancellation signal is required for this test.")
        yield ProviderTextDeltaEvent(delta="Hel")
        await signal.wait()
        signal.raise_if_cancelled()
        raise AssertionError("Signal should cancel before continuing.")


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
            ItemAttachmentModel.__table__,
            QueuedInputModel.__table__,
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
    agent_loader: FakeAgentLoader | None = None,
    model: str = "openrouter:test-model",
    provider: Provider | None = None,
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
            trace_id=None,
            root_agent_id="agent-1",
            parent_id=None,
            source_call_id=None,
            depth=0,
            agent_name="manfred",
            status=AgentStatus.PENDING,
            turn_count=0,
            waiting_for=[],
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
        user_repository=user_repository,
        tool_registry=ToolRegistry(tools=tools),
        mcp_manager=mcp_manager or FakeMcpManager(),
        provider_registry=ProviderRegistry(
            {
                "openrouter": provider
                or FakeProvider(
                    list(provider_responses),
                    stream_events=list(provider_streams or []),
                )
            }
        ),
        event_bus=event_bus,
        agent_loader=agent_loader or FakeAgentLoader(),
        max_delegation_depth=8,
        message_queue=SessionMessageQueue(
            queued_input_repository=QueuedInputRepository(db_session),
            item_repository=item_repository,
        ),
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
    async def failing_tool(
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> dict[str, object]:
        del context
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
async def test_runner_moves_to_waiting_for_human_tool(db_session: Session) -> None:
    runner, agent_id, event_types = make_runner(
        db_session,
        provider_responses=[
            ProviderResponse(
                output=[
                    ProviderFunctionCallOutputItem(
                        call_id="call-1",
                        name="ask_user",
                        arguments={"question": "Jakiego formatu oczekujesz?"},
                    )
                ],
                usage=ProviderUsage(input_tokens=8, output_tokens=3, total_tokens=11),
            )
        ],
        tools=[ask_user_tool],
    )

    result = await runner.run_agent(agent_id, last_agent_sequence=0)
    agent = AgentRepository(db_session).get(agent_id)
    stored_items = ItemRepository(db_session).list_by_agent(agent_id)

    assert result.ok is True
    assert result.status == "waiting"
    assert agent is not None
    assert agent.status == AgentStatus.WAITING
    assert len(agent.waiting_for) == 1
    assert agent.waiting_for[0].type == "human"
    assert agent.waiting_for[0].description == "Jakiego formatu oczekujesz?"
    assert [item.type.value for item in stored_items[1:]] == ["function_call"]
    assert event_types == [
        "agent.started",
        "turn.started",
        "generation.completed",
        "tool.called",
        "tool.completed",
        "turn.completed",
        "agent.waiting",
    ]


@pytest.mark.asyncio
async def test_runner_marks_non_stream_run_as_cancelled(db_session: Session) -> None:
    runner, agent_id, event_types = make_runner(
        db_session,
        provider_responses=[],
        tools=[],
        provider=BlockingProvider(),
    )
    signal = CancellationSignal()

    task = asyncio.create_task(
        runner.run_agent(
            agent_id,
            last_agent_sequence=0,
            signal=signal,
        )
    )
    await asyncio.sleep(0)
    signal.cancel()
    result = await task
    agent = AgentRepository(db_session).get(agent_id)

    assert result.status == "cancelled"
    assert result.ok is False
    assert agent is not None
    assert agent.status == AgentStatus.CANCELLED
    assert event_types == [
        "agent.started",
        "turn.started",
        "agent.cancelled",
    ]


@pytest.mark.asyncio
async def test_runner_marks_stream_run_as_cancelled(db_session: Session) -> None:
    runner, agent_id, event_types = make_runner(
        db_session,
        provider_responses=[],
        tools=[],
        provider=BlockingProvider(),
    )
    signal = CancellationSignal()
    streamed_event_types: list[str] = []
    streamed_deltas: list[str] = []

    async for event in runner.run_agent_stream(
        agent_id,
        last_agent_sequence=0,
        signal=signal,
    ):
        streamed_event_types.append(event.type)
        if isinstance(event, ProviderTextDeltaEvent):
            streamed_deltas.append(event.delta)
        if event.type == "text_delta":
            signal.cancel()

    agent = AgentRepository(db_session).get(agent_id)
    stored_items = ItemRepository(db_session).list_by_agent(agent_id)

    assert streamed_event_types == ["text_delta"]
    assert agent is not None
    assert agent.status == AgentStatus.CANCELLED
    assert [item.type.value for item in stored_items] == ["message", "message"]
    assert stored_items[-1].content == "".join(streamed_deltas)
    assert event_types == [
        "agent.started",
        "turn.started",
        "agent.cancelled",
    ]


@pytest.mark.asyncio
async def test_runner_persists_partial_stream_text_when_stream_ends_without_final_response(
    db_session: Session,
) -> None:
    runner, agent_id, event_types = make_runner(
        db_session,
        provider_responses=[],
        provider_streams=[
            [
                ProviderTextDeltaEvent(delta="Pierwsza linia. "),
                ProviderTextDeltaEvent(delta="Druga linia."),
            ]
        ],
        tools=[],
    )
    streamed_event_types: list[str] = []

    async for event in runner.run_agent_stream(
        agent_id,
        last_agent_sequence=0,
    ):
        streamed_event_types.append(event.type)

    agent = AgentRepository(db_session).get(agent_id)
    stored_items = ItemRepository(db_session).list_by_agent(agent_id)

    assert streamed_event_types == ["text_delta", "text_delta", "error"]
    assert agent is not None
    assert agent.status == AgentStatus.FAILED
    assert [item.type.value for item in stored_items] == ["message", "message"]
    assert stored_items[-1].content == "Pierwsza linia. Druga linia."
    assert event_types == [
        "agent.started",
        "turn.started",
        "agent.failed",
    ]


@pytest.mark.asyncio
async def test_runner_delegate_completes_child_and_parent(db_session: Session) -> None:
    runner, agent_id, event_types = make_runner(
        db_session,
        provider_responses=[
            ProviderResponse(
                output=[
                    ProviderFunctionCallOutputItem(
                        call_id="call-1",
                        name="delegate",
                        arguments={"agent_name": "helper", "task": "Rozwiaz to za mnie"},
                    )
                ],
                usage=ProviderUsage(input_tokens=8, output_tokens=3, total_tokens=11),
            ),
            ProviderResponse(
                output=[ProviderTextOutputItem(text="Wynik dziecka")],
                usage=ProviderUsage(input_tokens=6, output_tokens=4, total_tokens=10),
            ),
            ProviderResponse(
                output=[ProviderTextOutputItem(text="Wynik parenta")],
                usage=ProviderUsage(input_tokens=6, output_tokens=4, total_tokens=10),
            ),
        ],
        tools=[delegate_tool],
        agent_loader=FakeAgentLoader(
            {
                "helper": LoadedAgent(
                    agent_name="helper",
                    model="openrouter:test-model",
                    tools=[],
                    system_prompt="Pomagaj z zadaniami.",
                )
            }
        ),
    )

    result = await runner.run_agent(agent_id, last_agent_sequence=0)
    parent_items = ItemRepository(db_session).list_by_agent(agent_id)
    children = AgentRepository(db_session).list_children(agent_id)

    assert result.ok is True
    assert result.status == "completed"
    assert len(children) == 1
    assert children[0].parent_id == agent_id
    assert children[0].source_call_id == "call-1"
    assert children[0].depth == 1
    assert parent_items[2].type == ItemType.FUNCTION_CALL_OUTPUT
    assert parent_items[2].output == '{"ok": true, "output": "Wynik dziecka"}'
    assert event_types == [
        "agent.started",
        "turn.started",
        "generation.completed",
        "tool.called",
        "agent.started",
        "turn.started",
        "generation.completed",
        "turn.completed",
        "agent.completed",
        "tool.completed",
        "turn.completed",
        "turn.started",
        "generation.completed",
        "turn.completed",
        "agent.completed",
    ]


@pytest.mark.asyncio
async def test_runner_deliver_resumes_delegated_child_and_parent(db_session: Session) -> None:
    runner, agent_id, event_types = make_runner(
        db_session,
        provider_responses=[
            ProviderResponse(
                output=[
                    ProviderFunctionCallOutputItem(
                        call_id="call-parent",
                        name="delegate",
                        arguments={"agent_name": "helper", "task": "Dopytaj o brakujacy szczegol"},
                    )
                ],
                usage=ProviderUsage(input_tokens=8, output_tokens=3, total_tokens=11),
            ),
            ProviderResponse(
                output=[
                    ProviderFunctionCallOutputItem(
                        call_id="call-child",
                        name="ask_user",
                        arguments={"question": "Jaka wartosc mam wstawic?"},
                    )
                ],
                usage=ProviderUsage(input_tokens=7, output_tokens=2, total_tokens=9),
            ),
            ProviderResponse(
                output=[ProviderTextOutputItem(text="Dziecko zakonczone")],
                usage=ProviderUsage(input_tokens=6, output_tokens=4, total_tokens=10),
            ),
            ProviderResponse(
                output=[ProviderTextOutputItem(text="Parent zakonczony")],
                usage=ProviderUsage(input_tokens=6, output_tokens=4, total_tokens=10),
            ),
        ],
        tools=[delegate_tool, ask_user_tool],
        agent_loader=FakeAgentLoader(
            {
                "helper": LoadedAgent(
                    agent_name="helper",
                    model="openrouter:test-model",
                    tools=[ask_user_tool.definition],
                    system_prompt="Zbieraj brakujace dane.",
                )
            }
        ),
    )

    initial = await runner.run_agent(agent_id, last_agent_sequence=0)
    waiting_agent = AgentRepository(db_session).get(agent_id)

    assert initial.ok is True
    assert initial.status == "waiting"
    assert waiting_agent is not None
    assert waiting_agent.waiting_for[0].type == "agent"
    assert waiting_agent.waiting_for[0].call_id == "call-parent"
    assert waiting_agent.waiting_for[0].description == "Jaka wartosc mam wstawic?"
    assert waiting_agent.waiting_for[0].agent_id is not None

    resumed = await runner.deliver_result(
        agent_id,
        call_id="call-parent",
        result={"ok": True, "output": "42"},
    )
    parent_agent = AgentRepository(db_session).get(agent_id)
    child_agent = AgentRepository(db_session).get_child_by_source_call(agent_id, "call-parent")
    parent_items = ItemRepository(db_session).list_by_agent(agent_id)

    assert resumed.ok is True
    assert resumed.status == "completed"
    assert parent_agent is not None
    assert parent_agent.status == AgentStatus.COMPLETED
    assert parent_agent.waiting_for == []
    assert child_agent is not None
    assert child_agent.status == AgentStatus.COMPLETED
    assert parent_items[2].output == '{"ok": true, "output": "Dziecko zakonczone"}'
    assert parent_items[-1].content == "Parent zakonczony"
    assert "agent.waiting" in event_types
    assert event_types.count("agent.resumed") >= 2


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
    async def calculator(
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> dict[str, object]:
        del context
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


@pytest.mark.asyncio
async def test_runner_passes_tool_execution_context(db_session: Session) -> None:
    captured_context: ToolExecutionContext | None = None

    async def capture_tool(
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> dict[str, object]:
        nonlocal captured_context
        del arguments
        captured_context = context
        return {"ok": True, "output": "captured"}

    runner, agent_id, _event_types = make_runner(
        db_session,
        provider_responses=[
            ProviderResponse(
                output=[
                    ProviderFunctionCallOutputItem(
                        call_id="call-ctx",
                        name="capture",
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
                    name="capture",
                    description="Capture context",
                    parameters={"type": "object"},
                ),
                handler=capture_tool,
            )
        ],
    )

    result = await runner.run_agent(agent_id, last_agent_sequence=0)

    assert result.ok is True
    assert captured_context is not None
    assert captured_context.user_id == "user-1"
    assert captured_context.user_name == "User"
    assert captured_context.session_id == "session-1"
    assert captured_context.agent_id == "agent-1"
    assert captured_context.call_id == "call-ctx"
    assert captured_context.tool_name == "capture"
    assert captured_context.signal is not None


def test_runner_uses_last_new_user_message_for_run_input() -> None:
    now = utcnow()
    agent = Agent(
        id="agent-1",
        session_id="session-1",
        trace_id=None,
        root_agent_id="agent-1",
        parent_id=None,
        source_call_id=None,
        depth=0,
        agent_name="manfred",
        status=AgentStatus.PENDING,
        turn_count=0,
        waiting_for=[],
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
