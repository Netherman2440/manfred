import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.chat.schema import ChatEditRequest, ChatQueueRequest, ChatRequest, MessageInputItem
from app.config import Settings
from app.db.base import Base, utcnow
from app.db.models import AgentModel, ItemAttachmentModel, ItemModel, QueuedInputModel, SessionModel, UserModel
from app.domain import (
    Agent,
    AgentConfig,
    AgentStatus,
    Item,
    ItemType,
    MessageRole,
    QueuedInput,
    QueuedInputAttachment,
    Session as DomainSession,
    SessionStatus,
    User,
    WaitingForEntry,
)
from app.domain.repositories import AgentRepository, ItemRepository, QueuedInputRepository, SessionRepository, UserRepository
from app.events import EventBus
from app.providers import (
    ProviderFunctionCallOutputItem,
    ProviderRegistry,
    ProviderResponse,
    ProviderTextOutputItem,
    ProviderUsage,
)
from app.runtime.cancellation import ActiveRunRegistry
from app.runtime.message_queue import SessionMessageQueue
from app.runtime.runner import Runner
from app.services.agent_loader import LoadedAgent
from app.services.chat_attachments import ChatAttachmentStorageService, IncomingAttachment
from app.services.chat_service import ChatService, ChatServiceValidationError
from app.services.filesystem import WorkspaceLayoutService
from app.tools.definitions.ask_user import ask_user_tool
from app.tools.definitions.delegate import delegate_tool
from app.tools.registry import ToolRegistry
from tests.conftest import FakeFilesystemService


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


class CapturingProvider(FakeProvider):
    def __init__(self, responses: list[ProviderResponse]) -> None:
        super().__init__(responses)
        self.requests = []

    async def generate(self, request_data):  # noqa: ANN001
        self.requests.append(request_data)
        return await super().generate(request_data)


class FakeMcpManager:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def parse_name(self, prefixed_name: str) -> tuple[str, str] | None:
        del prefixed_name
        return None


class FakeAgentLoader:
    def __init__(
        self,
        *,
        root_agent: LoadedAgent,
        child_agents: dict[str, LoadedAgent] | None = None,
        root_agent_name: str | None = None,
    ) -> None:
        self._root_agent = root_agent
        self._child_agents = child_agents or {}
        self._root_agent_name = root_agent_name or root_agent.agent_name

    def load_agent(self, agent_path):  # noqa: ANN001
        del agent_path
        return self._root_agent

    def load_agent_by_name(self, agent_name: str) -> LoadedAgent:
        # Return root agent for the default/root agent name
        if agent_name == self._root_agent_name:
            return self._root_agent
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
async def test_process_chat_include_tool_result_returns_session_trace_for_delegation(
    db_session: Session,
    tmp_path: Path,
) -> None:
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
        user_repository=user_repository,
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
        message_queue=SessionMessageQueue(
            queued_input_repository=QueuedInputRepository(db_session),
            item_repository=item_repository,
        ),
        filesystem_service=FakeFilesystemService(),
    )
    chat_service = ChatService(
        session=db_session,
        settings=Settings(
            _env_file=None,
            DEFAULT_AGENT="manfred",
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
        queued_input_repository=QueuedInputRepository(db_session),
        runner=runner,
        active_run_registry=ActiveRunRegistry(),
        workspace_layout_service=WorkspaceLayoutService(
            repo_root=tmp_path,
            workspace_path=".agent_data",
        ),
        attachment_storage_service=ChatAttachmentStorageService(
            workspace_layout_service=WorkspaceLayoutService(
                repo_root=tmp_path,
                workspace_path=".agent_data",
            ),
            max_file_size=1024 * 1024,
        ),
        message_queue=SessionMessageQueue(
            queued_input_repository=QueuedInputRepository(db_session),
            item_repository=item_repository,
        ),
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


def test_load_session_creates_workspace_layout_for_new_session(db_session: Session, tmp_path: Path) -> None:
    user_repository = UserRepository(db_session)
    session_repository = SessionRepository(db_session)
    agent_repository = AgentRepository(db_session)
    item_repository = ItemRepository(db_session)
    workspace_layout_service = WorkspaceLayoutService(
        repo_root=tmp_path,
        workspace_path=".agent_data",
    )
    chat_service = ChatService(
        session=db_session,
        settings=Settings(
            _env_file=None,
            DEFAULT_AGENT="manfred",
            OPEN_ROUTER_LLM_MODEL="test-model",
            DEFAULT_USER_ID="default-user",
            DEFAULT_USER_NAME="Default User",
            LANGFUSE_ENABLED=False,
        ),
        agent_loader=FakeAgentLoader(
            root_agent=LoadedAgent(
                agent_name="manfred",
                model="openrouter:test-model",
                tools=[],
                system_prompt="Pomagaj uzytkownikowi.",
            )
        ),
        user_repository=user_repository,
        session_repository=session_repository,
        agent_repository=agent_repository,
        item_repository=item_repository,
        queued_input_repository=QueuedInputRepository(db_session),
        runner=object(),  # type: ignore[arg-type]
        active_run_registry=ActiveRunRegistry(),
        workspace_layout_service=workspace_layout_service,
        attachment_storage_service=ChatAttachmentStorageService(
            workspace_layout_service=workspace_layout_service,
            max_file_size=1024 * 1024,
        ),
        message_queue=SessionMessageQueue(
            queued_input_repository=QueuedInputRepository(db_session),
            item_repository=item_repository,
        ),
    )

    user = chat_service._ensure_default_user()
    session = chat_service._load_session(None, user)

    session_root = (
        tmp_path
        / ".agent_data"
        / "default-user"
        / "workspaces"
        / session.created_at.strftime("%Y")
        / session.created_at.strftime("%m")
        / session.created_at.strftime("%d")
        / session.id
    )
    assert (session_root / "files").is_dir()
    assert (session_root / "attachments").is_dir()
    assert (session_root / "plan.md").is_file()
    assert session.workspace_path == str(session_root)


def test_load_session_rejects_foreign_session(db_session: Session, tmp_path: Path) -> None:
    user_repository = UserRepository(db_session)
    session_repository = SessionRepository(db_session)
    agent_repository = AgentRepository(db_session)
    item_repository = ItemRepository(db_session)
    workspace_layout_service = WorkspaceLayoutService(
        repo_root=tmp_path,
        workspace_path=".agent_data",
    )
    chat_service = ChatService(
        session=db_session,
        settings=Settings(
            _env_file=None,
            DEFAULT_AGENT="manfred",
            OPEN_ROUTER_LLM_MODEL="test-model",
            DEFAULT_USER_ID="default-user",
            DEFAULT_USER_NAME="Default User",
            LANGFUSE_ENABLED=False,
        ),
        agent_loader=FakeAgentLoader(
            root_agent=LoadedAgent(
                agent_name="manfred",
                model="openrouter:test-model",
                tools=[],
                system_prompt="Pomagaj uzytkownikowi.",
            )
        ),
        user_repository=user_repository,
        session_repository=session_repository,
        agent_repository=agent_repository,
        item_repository=item_repository,
        queued_input_repository=QueuedInputRepository(db_session),
        runner=object(),  # type: ignore[arg-type]
        active_run_registry=ActiveRunRegistry(),
        workspace_layout_service=workspace_layout_service,
        attachment_storage_service=ChatAttachmentStorageService(
            workspace_layout_service=workspace_layout_service,
            max_file_size=1024 * 1024,
        ),
        message_queue=SessionMessageQueue(
            queued_input_repository=QueuedInputRepository(db_session),
            item_repository=item_repository,
        ),
    )

    now = utcnow()
    session_repository.save(
        DomainSession(
            id="foreign-session",
            user_id="other-user",
            root_agent_id=None,
            status=SessionStatus.ACTIVE,
            title=None,
            created_at=now,
            updated_at=now,
        )
    )

    user = chat_service._ensure_default_user()

    with pytest.raises(ChatServiceValidationError, match="Session not found: foreign-session"):
        chat_service._load_session("foreign-session", user)


@pytest.mark.asyncio
async def test_process_chat_persists_attachments_and_maps_them_to_provider_input(
    db_session: Session,
    tmp_path: Path,
) -> None:
    user_repository = UserRepository(db_session)
    session_repository = SessionRepository(db_session)
    agent_repository = AgentRepository(db_session)
    item_repository = ItemRepository(db_session)
    queued_input_repository = QueuedInputRepository(db_session)
    workspace_layout_service = WorkspaceLayoutService(
        repo_root=tmp_path,
        workspace_path=".agent_data",
    )
    capturing_provider = CapturingProvider(
        [ProviderResponse(output=[ProviderTextOutputItem(text="Odczytalem zalacznik.")])]
    )
    runner = Runner(
        agent_repository=agent_repository,
        session_repository=session_repository,
        item_repository=item_repository,
        user_repository=user_repository,
        tool_registry=ToolRegistry(tools=[]),
        mcp_manager=FakeMcpManager(),
        provider_registry=ProviderRegistry({"openrouter": capturing_provider}),
        event_bus=EventBus(),
        agent_loader=FakeAgentLoader(
            root_agent=LoadedAgent(
                agent_name="manfred",
                model="openrouter:test-model",
                tools=[],
                system_prompt="Pomagaj uzytkownikowi.",
            )
        ),
        max_delegation_depth=8,
        message_queue=SessionMessageQueue(
            queued_input_repository=queued_input_repository,
            item_repository=item_repository,
        ),
        filesystem_service=FakeFilesystemService(),
    )
    chat_service = ChatService(
        session=db_session,
        settings=Settings(
            _env_file=None,
            DEFAULT_AGENT="manfred",
            OPEN_ROUTER_LLM_MODEL="test-model",
            DEFAULT_USER_ID="default-user",
            DEFAULT_USER_NAME="Default User",
            LANGFUSE_ENABLED=False,
        ),
        agent_loader=FakeAgentLoader(
            root_agent=LoadedAgent(
                agent_name="manfred",
                model="openrouter:test-model",
                tools=[],
                system_prompt="Pomagaj uzytkownikowi.",
            )
        ),
        user_repository=user_repository,
        session_repository=session_repository,
        agent_repository=agent_repository,
        item_repository=item_repository,
        queued_input_repository=queued_input_repository,
        runner=runner,
        active_run_registry=ActiveRunRegistry(),
        workspace_layout_service=workspace_layout_service,
        attachment_storage_service=ChatAttachmentStorageService(
            workspace_layout_service=workspace_layout_service,
            max_file_size=1024 * 1024,
        ),
        message_queue=SessionMessageQueue(
            queued_input_repository=queued_input_repository,
            item_repository=item_repository,
        ),
    )

    response = await chat_service.process_chat(
        ChatRequest(input=[MessageInputItem(role="user", content="Przeczytaj plik")]),
        attachments=[
            IncomingAttachment(
                file_name="notes.txt",
                media_type="text/plain",
                content=b"hello attachment",
            )
        ],
    )

    assert response.status == "completed"
    session_items = item_repository.list_by_session(response.session_id)
    user_item = next(item for item in session_items if item.role == MessageRole.USER)
    assert len(user_item.attachments) == 1
    assert user_item.attachments[0].file_name == "notes.txt"
    assert user_item.attachments[0].path == "workspace/attachments/notes.txt"
    assert (workspace_layout_service.ensure_session_workspace(
        user=chat_service._ensure_default_user(),
        session=session_repository.get(response.session_id),
    ).attachments_dir / "notes.txt").is_file()
    assert len(capturing_provider.requests) == 1
    provider_input = capturing_provider.requests[0].input
    assert [item.type for item in provider_input] == ["message", "message"]
    assert "Attached file: notes.txt" in provider_input[1].content
    assert "path: workspace/attachments/notes.txt" in provider_input[1].content


@pytest.mark.asyncio
async def test_process_edit_rewinds_history_and_clears_pending_queue(
    db_session: Session,
    tmp_path: Path,
) -> None:
    user_repository = UserRepository(db_session)
    session_repository = SessionRepository(db_session)
    agent_repository = AgentRepository(db_session)
    item_repository = ItemRepository(db_session)
    queued_input_repository = QueuedInputRepository(db_session)
    workspace_layout_service = WorkspaceLayoutService(
        repo_root=tmp_path,
        workspace_path=".agent_data",
    )
    now = utcnow()
    user_repository.save(User(id="default-user", name="Default User", api_key_hash=None, created_at=now))
    session_repository.save(
        DomainSession(
            id="session-1",
            user_id="default-user",
            root_agent_id="agent-1",
            status=SessionStatus.ACTIVE,
            title=None,
            created_at=now,
            updated_at=now,
        )
    )
    agent_repository.save(
        Agent(
            id="agent-1",
            session_id="session-1",
            trace_id="trace-1",
            root_agent_id="agent-1",
            parent_id=None,
            source_call_id=None,
            depth=0,
            agent_name="manfred",
            status=AgentStatus.COMPLETED,
            turn_count=2,
            waiting_for=[],
            config=AgentConfig(
                model="openrouter:test-model",
                task="Pomagaj.",
                tools=[],
                temperature=None,
            ),
            created_at=now,
            updated_at=now,
        )
    )
    item_repository.save(
        Item(
            id="user-item",
            session_id="session-1",
            agent_id="agent-1",
            sequence=1,
            type=ItemType.MESSAGE,
            role=MessageRole.USER,
            content="Stara tresc",
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
            id="assistant-old",
            session_id="session-1",
            agent_id="agent-1",
            sequence=2,
            type=ItemType.MESSAGE,
            role=MessageRole.ASSISTANT,
            content="Stara odpowiedz",
            call_id=None,
            name=None,
            arguments_json=None,
            output=None,
            is_error=False,
            created_at=utcnow(),
        )
    )
    agent_repository.save(
        Agent(
            id="child-1",
            session_id="session-1",
            trace_id="trace-1",
            root_agent_id="agent-1",
            parent_id="agent-1",
            source_call_id="call-child",
            depth=1,
            agent_name="research",
            status=AgentStatus.COMPLETED,
            turn_count=1,
            waiting_for=[],
            config=AgentConfig(
                model="openrouter:test-model",
                task="Research",
                tools=[],
                temperature=None,
            ),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    )
    item_repository.save(
        Item(
            id="child-item",
            session_id="session-1",
            agent_id="child-1",
            sequence=1,
            type=ItemType.MESSAGE,
            role=MessageRole.ASSISTANT,
            content="Dane dziecka",
            call_id=None,
            name=None,
            arguments_json=None,
            output=None,
            is_error=False,
            created_at=utcnow(),
        )
    )
    queued_input_repository.save(
        QueuedInput(
            id="queue-1",
            session_id="session-1",
            agent_id="agent-1",
            message="Czeka w kolejce",
            attachments=[
                QueuedInputAttachment(
                    file_name="pending.txt",
                    media_type="text/plain",
                    size_bytes=3,
                    path="input/pending.txt",
                )
            ],
            accepted_at=utcnow(),
        )
    )
    runner = Runner(
        agent_repository=agent_repository,
        session_repository=session_repository,
        item_repository=item_repository,
        user_repository=user_repository,
        tool_registry=ToolRegistry(tools=[]),
        mcp_manager=FakeMcpManager(),
        provider_registry=ProviderRegistry(
            {"openrouter": FakeProvider([ProviderResponse(output=[ProviderTextOutputItem(text="Nowa odpowiedz")])])}
        ),
        event_bus=EventBus(),
        agent_loader=FakeAgentLoader(
            root_agent=LoadedAgent(
                agent_name="manfred",
                model="openrouter:test-model",
                tools=[],
                system_prompt="Pomagaj uzytkownikowi.",
            )
        ),
        max_delegation_depth=8,
        message_queue=SessionMessageQueue(
            queued_input_repository=queued_input_repository,
            item_repository=item_repository,
        ),
        filesystem_service=FakeFilesystemService(),
    )
    chat_service = ChatService(
        session=db_session,
        settings=Settings(
            _env_file=None,
            DEFAULT_AGENT="manfred",
            OPEN_ROUTER_LLM_MODEL="test-model",
            DEFAULT_USER_ID="default-user",
            DEFAULT_USER_NAME="Default User",
            LANGFUSE_ENABLED=False,
        ),
        agent_loader=FakeAgentLoader(
            root_agent=LoadedAgent(
                agent_name="manfred",
                model="openrouter:test-model",
                tools=[],
                system_prompt="Pomagaj uzytkownikowi.",
            )
        ),
        user_repository=user_repository,
        session_repository=session_repository,
        agent_repository=agent_repository,
        item_repository=item_repository,
        queued_input_repository=queued_input_repository,
        runner=runner,
        active_run_registry=ActiveRunRegistry(),
        workspace_layout_service=workspace_layout_service,
        attachment_storage_service=ChatAttachmentStorageService(
            workspace_layout_service=workspace_layout_service,
            max_file_size=1024 * 1024,
        ),
        message_queue=SessionMessageQueue(
            queued_input_repository=queued_input_repository,
            item_repository=item_repository,
        ),
    )

    response = await chat_service.process_edit(
        "session-1",
        "user-item",
        ChatEditRequest(message="Nowa tresc"),
    )

    assert response.status == "completed"
    session_items = item_repository.list_by_session_chronological("session-1")
    assert [item.id for item in session_items] == ["user-item", session_items[-1].id]
    assert session_items[0].content == "Nowa tresc"
    assert session_items[0].edited_at is not None
    assert session_items[-1].content == "Nowa odpowiedz"
    assert item_repository.get("assistant-old") is None
    assert item_repository.get("child-item") is None
    assert agent_repository.get("child-1") is None
    assert queued_input_repository.get_pending_count("session-1", "agent-1") == 0


@pytest.mark.asyncio
async def test_process_queue_persists_pending_input_for_waiting_root_agent(
    db_session: Session,
    tmp_path: Path,
) -> None:
    user_repository = UserRepository(db_session)
    session_repository = SessionRepository(db_session)
    agent_repository = AgentRepository(db_session)
    item_repository = ItemRepository(db_session)
    queued_input_repository = QueuedInputRepository(db_session)
    workspace_layout_service = WorkspaceLayoutService(
        repo_root=tmp_path,
        workspace_path=".agent_data",
    )
    now = utcnow()
    user_repository.save(User(id="default-user", name="Default User", api_key_hash=None, created_at=now))
    session_repository.save(
        DomainSession(
            id="session-queue",
            user_id="default-user",
            root_agent_id="agent-queue",
            status=SessionStatus.ACTIVE,
            title=None,
            created_at=now,
            updated_at=now,
        )
    )
    agent_repository.save(
        Agent(
            id="agent-queue",
            session_id="session-queue",
            trace_id="trace-queue",
            root_agent_id="agent-queue",
            parent_id=None,
            source_call_id=None,
            depth=0,
            agent_name="manfred",
            status=AgentStatus.WAITING,
            turn_count=1,
            waiting_for=[
                WaitingForEntry(
                    call_id="ask-1",
                    type="human",
                    name="ask_user",
                    description="Doprecyzuj zakres",
                    agent_id="agent-queue",
                )
            ],
            config=AgentConfig(
                model="openrouter:test-model",
                task="Pomagaj.",
                tools=[],
                temperature=None,
            ),
            created_at=now,
            updated_at=now,
        )
    )
    chat_service = ChatService(
        session=db_session,
        settings=Settings(
            _env_file=None,
            DEFAULT_AGENT="manfred",
            OPEN_ROUTER_LLM_MODEL="test-model",
            DEFAULT_USER_ID="default-user",
            DEFAULT_USER_NAME="Default User",
            LANGFUSE_ENABLED=False,
        ),
        agent_loader=FakeAgentLoader(
            root_agent=LoadedAgent(
                agent_name="manfred",
                model="openrouter:test-model",
                tools=[],
                system_prompt="Pomagaj uzytkownikowi.",
            )
        ),
        user_repository=user_repository,
        session_repository=session_repository,
        agent_repository=agent_repository,
        item_repository=item_repository,
        queued_input_repository=queued_input_repository,
        runner=object(),  # type: ignore[arg-type]
        active_run_registry=ActiveRunRegistry(),
        workspace_layout_service=workspace_layout_service,
        attachment_storage_service=ChatAttachmentStorageService(
            workspace_layout_service=workspace_layout_service,
            max_file_size=1024 * 1024,
        ),
        message_queue=SessionMessageQueue(
            queued_input_repository=queued_input_repository,
            item_repository=item_repository,
        ),
    )

    response = await chat_service.process_queue(
        "session-queue",
        ChatQueueRequest(message="Nowa wiadomosc w kolejce"),
        attachments=[
            IncomingAttachment(
                file_name="queue.txt",
                media_type="text/plain",
                content=b"queued",
            )
        ],
    )

    assert response.session_id == "session-queue"
    assert response.queue_position == 1
    pending = queued_input_repository.get_pending_for_session_agent("session-queue", "agent-queue")
    assert len(pending) == 1
    assert pending[0].message == "Nowa wiadomosc w kolejce"
    assert pending[0].attachments[0].path == "workspace/attachments/queue.txt"
