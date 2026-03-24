import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.tools.delegate import delegate_handler, delegate_tool
from app.agent.tools.send_message import send_message_handler, send_message_tool
from app.db.base import Base
from app.db.models import AttachmentModel, AgentModel, ItemModel, SessionModel, UserModel
from app.db.repositories.agent_repository import AgentRepository
from app.db.repositories.item_repository import ItemRepository
from app.db.repositories.session_repository import SessionRepository
from app.db.repositories.user_repository import UserRepository
from app.domain import (
    Agent,
    AgentConfig,
    AgentStatus,
    FunctionToolDefinition,
    ItemType,
    MessageRole,
    ProviderFunctionCall,
    ProviderResponse,
    ProviderTextOutput,
    Session,
    Tool,
    ToolRegistry,
    WaitingFor,
    deliver_one,
    start_agent,
    wait_for_many,
)
from app.runtime.runner import AgentRunner
from app.services.observability import ObservabilityService
from app.workspace import AgentTemplateLoader


class QueueProvider:
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = list(responses)
        self.inputs = []

    def generate(self, provider_input: object) -> ProviderResponse:
        self.inputs.append(provider_input)
        if not self._responses:
            raise AssertionError("No queued provider response left.")
        return self._responses.pop(0)


async def noop_handler(args: dict[str, object], signal: object | None = None) -> dict[str, object]:
    del args, signal
    return {"ok": True, "output": "noop"}


class AgentTemplateLoaderTest(unittest.TestCase):
    def test_loads_template_and_uses_default_model(self) -> None:
        registry = ToolRegistry(max_log_value_length=100)
        registry.register(send_message_tool)

        with tempfile.TemporaryDirectory() as tempdir:
            template_path = Path(tempdir) / "worker.agent.md"
            template_path.write_text(
                "---\nname: worker\ntools:\n  - send_message\n---\nWorker prompt.\n",
                encoding="utf-8",
            )
            loader = AgentTemplateLoader(
                templates_dir=Path(tempdir),
                tool_registry=registry,
                default_model="gpt-test",
            )

            template = loader.load("worker")

        self.assertEqual(template.name, "worker")
        self.assertEqual(template.model, "gpt-test")
        self.assertEqual(template.tool_names, ("send_message",))
        self.assertEqual(template.system_prompt, "Worker prompt.")


class AgentDomainTransitionTest(unittest.TestCase):
    def test_wait_and_deliver_transitions(self) -> None:
        agent = Agent(
            id="agent-1",
            session_id="session-1",
            root_agent_id="agent-1",
            parent_id=None,
            source_call_id=None,
            depth=0,
            status=AgentStatus.PENDING,
            waiting_for=(),
            result=None,
            error=None,
            turn_count=0,
            config=AgentConfig(model="gpt-test", task="prompt"),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        running = start_agent(agent)
        waiting = wait_for_many(
            running,
            [
                WaitingFor(
                    call_id="call-1",
                    type="tool",
                    name="ask_user",
                    description="Need input",
                )
            ],
        )
        resumed = deliver_one(waiting, "call-1")

        self.assertEqual(waiting.status, AgentStatus.WAITING)
        self.assertEqual(waiting.waiting_for[0].call_id, "call-1")
        self.assertEqual(resumed.status, AgentStatus.RUNNING)
        self.assertEqual(resumed.waiting_for, ())


class SubagentToolValidationTest(unittest.IsolatedAsyncioTestCase):
    async def test_delegate_validation_rejects_missing_task(self) -> None:
        result = await delegate_handler({"agent": "azazel", "task": ""})
        self.assertFalse(result["ok"])

    async def test_send_message_validation_rejects_missing_target(self) -> None:
        result = await send_message_handler({"to": "", "message": "hello"})
        self.assertFalse(result["ok"])


class AgentRunnerSubagentTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "test.db"
        engine = create_engine(f"sqlite:///{db_path}", future=True, connect_args={"check_same_thread": False})
        session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
        Base.metadata.create_all(engine)

        self.user_repository = UserRepository(session_factory=session_factory)
        self.session_repository = SessionRepository(session_factory=session_factory)
        self.agent_repository = AgentRepository(session_factory=session_factory)
        self.item_repository = ItemRepository(session_factory=session_factory)
        self.user = self.user_repository.create("Test User", user_id="user-1")
        self.session = self.session_repository.create(user_id=self.user.id, session_id="session-1")

        self.templates_dir = Path(self.tempdir.name) / "agents"
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.registry = ToolRegistry(max_log_value_length=100)
        self.registry.register(delegate_tool)
        self.registry.register(send_message_tool)
        self.registry.register(
            Tool(
                type="human",
                definition=FunctionToolDefinition(
                    name="ask_user",
                    description="Ask the user for missing input.",
                    parameters={"type": "object"},
                ),
                handler=noop_handler,
            )
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_template(self, name: str, tools: list[str], prompt: str) -> None:
        (self.templates_dir / f"{name}.agent.md").write_text(
            "---\n"
            f"name: {name}\n"
            "tools:\n"
            + "".join(f"  - {tool}\n" for tool in tools)
            + "---\n"
            f"{prompt}\n",
            encoding="utf-8",
        )

    def _build_runner(self, provider: QueueProvider) -> AgentRunner:
        loader = AgentTemplateLoader(
            templates_dir=self.templates_dir,
            tool_registry=self.registry,
            default_model="gpt-test",
        )
        return AgentRunner(
            agent_repository=self.agent_repository,
            session_repository=self.session_repository,
            item_repository=self.item_repository,
            tool_registry=self.registry,
            provider=provider,
            observability=ObservabilityService(),
            max_turn_count=10,
            subagent_max_turn_count=10,
            max_agent_depth=3,
            agent_template_loader=loader,
        )

    def _create_agent(self, *, config: AgentConfig) -> Agent:
        agent = self.agent_repository.create(session_id=self.session.id, config=config)
        self.item_repository.create(
            session_id=self.session.id,
            agent_id=agent.id,
            sequence=1,
            item_type=ItemType.MESSAGE,
            role=MessageRole.USER,
            content="Start",
        )
        return agent

    async def test_delegate_waiting_child_resumes_parent(self) -> None:
        self._write_template("mandfred", ["delegate"], "Root prompt")
        self._write_template("worker", ["ask_user"], "Worker prompt")

        runner = self._build_runner(
            QueueProvider(
                [
                    ProviderResponse(
                        output=[
                            ProviderFunctionCall(
                                call_id="root-call-1",
                                name="delegate",
                                arguments={"agent": "worker", "task": "Do the task"},
                            )
                        ]
                    ),
                    ProviderResponse(
                        output=[
                            ProviderFunctionCall(
                                call_id="child-call-1",
                                name="ask_user",
                                arguments={"question": "Need approval"},
                            )
                        ]
                    ),
                    ProviderResponse(output=[ProviderTextOutput(text="Child finished")]),
                    ProviderResponse(output=[ProviderTextOutput(text="Parent finished")]),
                ]
            )
        )

        root_agent = self._create_agent(config=AgentConfig(model="gpt-test", task="Root prompt", tool_names=("delegate",)))

        root_run = await runner.run_agent(root_agent.id)
        self.assertEqual(root_run.status, "waiting")
        self.assertEqual(root_run.agent.waiting_for[0].type, "agent")
        child_id = root_run.agent.waiting_for[0].agent_id
        self.assertIsNotNone(child_id)

        child_run = await runner.deliver_result(
            agent_id=child_id or "",
            call_id="child-call-1",
            output="Approved",
            is_error=False,
        )
        self.assertEqual(child_run.status, "completed")

        updated_root = self.agent_repository.get_by_id(root_agent.id)
        self.assertIsNotNone(updated_root)
        assert updated_root is not None
        self.assertEqual(updated_root.status, AgentStatus.COMPLETED)
        root_items = self.item_repository.list_by_agent(root_agent.id)
        self.assertIn("Parent finished", [item.content for item in root_items if item.content is not None])

    async def test_send_message_writes_system_message_to_target_agent(self) -> None:
        self._write_template("mandfred", ["delegate"], "Root prompt")
        runner = self._build_runner(
            QueueProvider(
                [
                    ProviderResponse(
                        output=[
                            ProviderFunctionCall(
                                call_id="msg-call-1",
                                name="send_message",
                                arguments={"to": "target-agent", "message": "hello from sender"},
                            )
                        ]
                    ),
                    ProviderResponse(output=[ProviderTextOutput(text="sent")]),
                ]
            )
        )

        sender = self._create_agent(config=AgentConfig(model="gpt-test", task="Sender prompt", tool_names=("send_message",)))
        target = self.agent_repository.create(
            session_id=self.session.id,
            agent_id="target-agent",
            config=AgentConfig(model="gpt-test", task="Target prompt"),
        )

        result = await runner.run_agent(sender.id)
        self.assertEqual(result.status, "completed")

        target_items = self.item_repository.list_by_agent(target.id)
        system_messages = [item.content for item in target_items if item.role == MessageRole.SYSTEM]
        self.assertEqual(system_messages, ["hello from sender"])


if __name__ == "__main__":
    unittest.main()
