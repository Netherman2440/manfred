import unittest
from datetime import UTC, datetime, timedelta

from app.domain import (
    Agent,
    AgentConfig,
    AgentStatus,
    Attachment,
    AttachmentKind,
    Item,
    ItemType,
    MessageRole,
    Session,
    SessionStatus,
    TranscriptionStatus,
    WaitingFor,
)
from app.services.session_history import SessionHistoryService


class StubSessionRepository:
    def __init__(self, sessions: list[Session]) -> None:
        self._sessions = {session.id: session for session in sessions}

    def list_by_user(self, user_id: str) -> list[Session]:
        return [session for session in self._sessions.values() if session.user_id == user_id]

    def get_by_id(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)


class StubAgentRepository:
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents

    def list_by_session(self, session_id: str) -> list[Agent]:
        return [agent for agent in self._agents if agent.session_id == session_id]


class StubItemRepository:
    def __init__(self, items_by_session: dict[str, list[Item]]) -> None:
        self._items_by_session = items_by_session

    def list_by_session(self, session_id: str) -> list[Item]:
        return list(self._items_by_session.get(session_id, []))


class StubAttachmentRepository:
    def __init__(self, attachments_by_session: dict[str, list[Attachment]]) -> None:
        self._attachments_by_session = attachments_by_session

    def list_by_session(self, session_id: str) -> list[Attachment]:
        return list(self._attachments_by_session.get(session_id, []))


class SessionHistoryServiceTest(unittest.TestCase):
    def test_list_sessions_sorts_by_updated_at_and_uses_summary_fallback(self) -> None:
        timestamp = datetime.now(UTC)
        older_session = Session(
            id="sess-older",
            user_id="user-123",
            root_agent_id="agent-root",
            status=SessionStatus.ACTIVE,
            summary=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        newer_session = Session(
            id="sess-newer",
            user_id="user-123",
            root_agent_id="agent-root",
            status=SessionStatus.ARCHIVED,
            summary="Gotowe podsumowanie",
            created_at=timestamp + timedelta(minutes=1),
            updated_at=timestamp + timedelta(minutes=2),
        )
        items_by_session = {
            "sess-older": [
                Item(
                    id="item-1",
                    session_id="sess-older",
                    agent_id="agent-root",
                    sequence=1,
                    type=ItemType.MESSAGE,
                    role=MessageRole.USER,
                    content="   Pierwsza wiadomosc usera. \n\n attachments:\n - input/sess-older/file.pdf",
                    call_id=None,
                    name=None,
                    arguments_json=None,
                    output=None,
                    is_error=False,
                    created_at=timestamp,
                )
            ]
        }

        service = SessionHistoryService(
            session_repository=StubSessionRepository([older_session, newer_session]),
            agent_repository=StubAgentRepository([]),
            item_repository=StubItemRepository(items_by_session),
            attachment_repository=StubAttachmentRepository({}),
        )

        response = service.list_sessions("user-123")

        self.assertEqual([session.id for session in response.sessions], ["sess-newer", "sess-older"])
        self.assertEqual(response.sessions[0].summary, "Gotowe podsumowanie")
        self.assertEqual(
            response.sessions[1].summary,
            "Pierwsza wiadomosc usera. attachments: - input/sess-older/file.pdf",
        )

    def test_get_session_detail_builds_entries_and_waiting_state(self) -> None:
        timestamp = datetime.now(UTC)
        session = Session(
            id="sess-123",
            user_id="user-123",
            root_agent_id="agent-root",
            status=SessionStatus.ACTIVE,
            summary=None,
            created_at=timestamp,
            updated_at=timestamp + timedelta(minutes=5),
        )
        root_agent = Agent(
            id="agent-root",
            session_id=session.id,
            root_agent_id="agent-root",
            parent_id=None,
            source_call_id=None,
            depth=0,
            status=AgentStatus.WAITING,
            waiting_for=(
                WaitingFor(
                    call_id="call-2",
                    type="agent",
                    name="delegate",
                    description='Waiting for agent "worker" to complete.',
                    agent_id="agent-child",
                ),
            ),
            result=None,
            error=None,
            turn_count=2,
            config=AgentConfig(model="gpt-test", task="Prompt"),
            created_at=timestamp,
            updated_at=timestamp + timedelta(minutes=5),
        )
        items = [
            Item(
                id="item-user-1",
                session_id=session.id,
                agent_id="agent-root",
                sequence=1,
                type=ItemType.MESSAGE,
                role=MessageRole.USER,
                content="Pierwsze pytanie",
                call_id=None,
                name=None,
                arguments_json=None,
                output=None,
                is_error=False,
                created_at=timestamp,
            ),
            Item(
                id="item-assistant-1",
                session_id=session.id,
                agent_id="agent-root",
                sequence=2,
                type=ItemType.MESSAGE,
                role=MessageRole.ASSISTANT,
                content="Pierwsza odpowiedz",
                call_id=None,
                name=None,
                arguments_json=None,
                output=None,
                is_error=False,
                created_at=timestamp + timedelta(seconds=5),
            ),
            Item(
                id="item-user-2",
                session_id=session.id,
                agent_id="agent-root",
                sequence=3,
                type=ItemType.MESSAGE,
                role=MessageRole.USER,
                content="Drugie pytanie",
                call_id=None,
                name=None,
                arguments_json=None,
                output=None,
                is_error=False,
                created_at=timestamp + timedelta(seconds=10),
            ),
            Item(
                id="item-call-2",
                session_id=session.id,
                agent_id="agent-root",
                sequence=4,
                type=ItemType.FUNCTION_CALL,
                role=None,
                content=None,
                call_id="call-2",
                name="delegate",
                arguments_json='{"agent": "worker", "task": "Sprawdz dane"}',
                output=None,
                is_error=False,
                created_at=timestamp + timedelta(seconds=15),
            ),
        ]
        attachments = [
            Attachment(
                id="att-user-1",
                session_id=session.id,
                agent_id="agent-root",
                item_id="item-user-1",
                kind=AttachmentKind.DOCUMENT,
                mime_type="application/pdf",
                original_filename="brief.pdf",
                stored_filename="brief.pdf",
                workspace_path="input/sess-123/brief.pdf",
                size_bytes=123,
                source="file_picker",
                transcription_status=TranscriptionStatus.NOT_APPLICABLE,
                transcription_text=None,
                created_at=timestamp,
            ),
            Attachment(
                id="att-call-2",
                session_id=session.id,
                agent_id="agent-root",
                item_id="item-call-2",
                kind=AttachmentKind.OTHER,
                mime_type="application/json",
                original_filename="delegate.json",
                stored_filename="delegate.json",
                workspace_path="input/sess-123/delegate.json",
                size_bytes=45,
                source="system",
                transcription_status=TranscriptionStatus.NOT_APPLICABLE,
                transcription_text=None,
                created_at=timestamp + timedelta(seconds=15),
            ),
        ]

        service = SessionHistoryService(
            session_repository=StubSessionRepository([session]),
            agent_repository=StubAgentRepository([root_agent]),
            item_repository=StubItemRepository({session.id: items}),
            attachment_repository=StubAttachmentRepository({session.id: attachments}),
        )

        response = service.get_session_detail("user-123", session.id)

        self.assertEqual(response.summary, "Pierwsze pytanie")
        self.assertEqual(len(response.entries), 4)
        self.assertEqual(response.entries[0].type, "message")
        self.assertEqual(response.entries[0].attachments[0].id, "att-user-1")
        self.assertEqual(response.entries[1].type, "agent_response")
        self.assertEqual(response.entries[1].status, "completed")
        self.assertEqual(response.entries[1].output[0]["text"], "Pierwsza odpowiedz")
        self.assertEqual(response.entries[2].type, "message")
        self.assertEqual(response.entries[3].type, "agent_response")
        self.assertEqual(response.entries[3].status, "waiting")
        self.assertEqual(response.entries[3].output[0]["type"], "function_call")
        self.assertEqual(response.entries[3].attachments[0].id, "att-call-2")
        self.assertEqual(response.entries[3].waiting_for[0].call_id, "call-2")


if __name__ == "__main__":
    unittest.main()
