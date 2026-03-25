import unittest
from datetime import UTC, datetime

from app.domain import (
    Agent,
    AgentConfig,
    AgentStatus,
    Attachment,
    AttachmentKind,
    ChatRequest,
    Session,
    SessionStatus,
    ToolRegistry,
    TranscriptionStatus,
    User,
)
from app.domain.item import Item
from app.domain.types import ItemType, MessageRole
from app.services.attachments import ChatInputBuilder
from app.services.chat_service import ChatService
from app.services.observability import ObservabilityService


class StubItemRepository:
    def __init__(self) -> None:
        self.created_items: list[Item] = []

    def get_last_sequence(self, agent_id: str) -> int:
        del agent_id
        return 0

    def create(
        self,
        *,
        session_id: str,
        agent_id: str,
        sequence: int,
        item_type: ItemType,
        role: MessageRole | None = None,
        content: str | None = None,
        **_: object,
    ) -> Item:
        item = Item(
            id="item-123",
            session_id=session_id,
            agent_id=agent_id,
            sequence=sequence,
            type=item_type,
            role=role,
            content=content,
            call_id=None,
            name=None,
            arguments_json=None,
            output=None,
            is_error=False,
            created_at=datetime.now(UTC),
        )
        self.created_items.append(item)
        return item


class StubAttachmentService:
    def __init__(self, attachments: list[Attachment]) -> None:
        self._attachments = attachments
        self.requested_ids: tuple[str, ...] = ()

    def get_for_session(self, *, session_id: str, attachment_ids: tuple[str, ...]) -> list[Attachment]:
        del session_id
        self.requested_ids = tuple(attachment_ids)
        return list(self._attachments)

    async def ensure_transcriptions(self, attachments: list[Attachment]) -> list[Attachment]:
        return attachments

    def assign_to_item(self, attachments: list[Attachment], *, agent_id: str, item_id: str) -> list[Attachment]:
        return [
            Attachment(
                id=attachment.id,
                session_id=attachment.session_id,
                agent_id=agent_id,
                item_id=item_id,
                kind=attachment.kind,
                mime_type=attachment.mime_type,
                original_filename=attachment.original_filename,
                stored_filename=attachment.stored_filename,
                workspace_path=attachment.workspace_path,
                size_bytes=attachment.size_bytes,
                source=attachment.source,
                transcription_status=attachment.transcription_status,
                transcription_text=attachment.transcription_text,
                created_at=attachment.created_at,
            )
            for attachment in attachments
        ]


class StubConversationContextService:
    def __init__(self, *, session: Session, agent: Agent, user: User) -> None:
        self._session = session
        self._agent = agent
        self._user = user

    def ensure_default_user(self) -> User:
        return self._user

    def load_or_create_session(self, session_id: str | None, user: User) -> Session:
        del session_id, user
        return self._session

    def load_or_create_root_agent(self, session: Session) -> Agent:
        del session
        return self._agent


class StubAgentRunner:
    async def run_agent(self, agent_id: str) -> object:
        raise NotImplementedError


class StubAgentRepository:
    def get_by_id(self, agent_id: str) -> Agent | None:
        del agent_id
        return None


class StubRunResult:
    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.error = None


class ChatServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_chat_turn_builds_message_with_attachment_references_and_transcriptions(self) -> None:
        timestamp = datetime.now(UTC)
        user = User(id="user-123", name="Default User", api_key_hash=None, created_at=timestamp)
        session = Session(
            id="sess-123",
            user_id=user.id,
            root_agent_id="agent-123",
            status=SessionStatus.ACTIVE,
            summary=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        agent_config = AgentConfig(model="gpt-test", task="system prompt")
        agent = Agent(
            id="agent-123",
            session_id=session.id,
            root_agent_id="agent-123",
            parent_id=None,
            source_call_id=None,
            depth=0,
            status=AgentStatus.PENDING,
            waiting_for=(),
            result=None,
            error=None,
            turn_count=0,
            config=agent_config,
            created_at=timestamp,
            updated_at=timestamp,
        )
        attachment = Attachment(
            id="att-123",
            session_id=session.id,
            agent_id=None,
            item_id=None,
            kind=AttachmentKind.AUDIO,
            mime_type="audio/webm",
            original_filename="voice.webm",
            stored_filename="20260323_voice.webm",
            workspace_path="input/sess-123/20260323_voice.webm",
            size_bytes=12,
            source="voice_recording",
            transcription_status=TranscriptionStatus.COMPLETED,
            transcription_text="Przygotuj podsumowanie nagrania.",
            created_at=timestamp,
        )

        attachment_service = StubAttachmentService([attachment])
        service = ChatService(
            item_repository=StubItemRepository(),
            agent_repository=StubAgentRepository(),
            attachment_service=attachment_service,
            tool_registry=ToolRegistry(max_log_value_length=100),
            agent_runner=StubAgentRunner(),
            observability=ObservabilityService(),
            chat_input_builder=ChatInputBuilder(),
            conversation_context=StubConversationContextService(session=session, agent=agent, user=user),
        )

        chat_turn = await service.prepare_chat_turn(
            ChatRequest(
                message="Przeanalizuj zalacznik.",
                session_id=session.id,
                attachment_ids=(attachment.id,),
            )
        )

        self.assertEqual(attachment_service.requested_ids, (attachment.id,))
        self.assertIn("Przeanalizuj zalacznik.", chat_turn.user_item.content or "")
        self.assertIn("attachments:", chat_turn.user_item.content or "")
        self.assertIn("audio_transcriptions:", chat_turn.user_item.content or "")
        self.assertIn(attachment.workspace_path, chat_turn.user_item.content or "")
        self.assertEqual(chat_turn.attachments[0].item_id, chat_turn.user_item.id)
        self.assertEqual(chat_turn.attachments[0].agent_id, agent.id)

    async def test_process_chat_returns_function_call_results_in_output(self) -> None:
        timestamp = datetime.now(UTC)
        user = User(id="user-123", name="Default User", api_key_hash=None, created_at=timestamp)
        session = Session(
            id="sess-123",
            user_id=user.id,
            root_agent_id="agent-123",
            status=SessionStatus.ACTIVE,
            summary=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        agent = Agent(
            id="agent-123",
            session_id=session.id,
            root_agent_id="agent-123",
            parent_id=None,
            source_call_id=None,
            depth=0,
            status=AgentStatus.COMPLETED,
            waiting_for=(),
            result=None,
            error=None,
            turn_count=1,
            config=AgentConfig(model="gpt-test", task="system prompt"),
            created_at=timestamp,
            updated_at=timestamp,
        )

        class ProcessItemRepository(StubItemRepository):
            def get_last_sequence(self, agent_id: str) -> int:
                del agent_id
                return 1

            def list_by_agent(self, agent_id: str) -> list[Item]:
                del agent_id
                return [
                    Item(
                        id="item-1",
                        session_id=session.id,
                        agent_id=agent.id,
                        sequence=1,
                        type=ItemType.MESSAGE,
                        role=MessageRole.USER,
                        content="Start",
                        call_id=None,
                        name=None,
                        arguments_json=None,
                        output=None,
                        is_error=False,
                        created_at=timestamp,
                    ),
                    Item(
                        id="item-2",
                        session_id=session.id,
                        agent_id=agent.id,
                        sequence=2,
                        type=ItemType.FUNCTION_CALL,
                        role=None,
                        content=None,
                        call_id="call-1",
                        name="delegate",
                        arguments_json='{"agent": "azazel"}',
                        output=None,
                        is_error=False,
                        created_at=timestamp,
                    ),
                    Item(
                        id="item-3",
                        session_id=session.id,
                        agent_id=agent.id,
                        sequence=3,
                        type=ItemType.FUNCTION_CALL_OUTPUT,
                        role=None,
                        content=None,
                        call_id="call-1",
                        name="delegate",
                        arguments_json=None,
                        output='"Child finished"',
                        is_error=False,
                        created_at=timestamp,
                    ),
                    Item(
                        id="item-4",
                        session_id=session.id,
                        agent_id=agent.id,
                        sequence=4,
                        type=ItemType.MESSAGE,
                        role=MessageRole.ASSISTANT,
                        content="Done",
                        call_id=None,
                        name=None,
                        arguments_json=None,
                        output=None,
                        is_error=False,
                        created_at=timestamp,
                    ),
                ]

        class ProcessAgentRunner(StubAgentRunner):
            async def run_agent(self, agent_id: str) -> StubRunResult:
                del agent_id
                return StubRunResult(agent)

        service = ChatService(
            item_repository=ProcessItemRepository(),
            agent_repository=StubAgentRepository(),
            attachment_service=StubAttachmentService([]),
            tool_registry=ToolRegistry(max_log_value_length=100),
            agent_runner=ProcessAgentRunner(),
            observability=ObservabilityService(),
            chat_input_builder=ChatInputBuilder(),
            conversation_context=StubConversationContextService(session=session, agent=agent, user=user),
        )

        response = await service.process_chat(ChatRequest(message="Run", session_id=session.id))

        self.assertEqual(response.output[0]["type"], "function_call")
        self.assertEqual(response.output[1]["type"], "function_call_output")
        self.assertEqual(response.output[1]["callId"], "call-1")
        self.assertEqual(response.output[1]["output"], "Child finished")
        self.assertFalse(response.output[1]["isError"])
        self.assertEqual(response.output[2]["type"], "text")
