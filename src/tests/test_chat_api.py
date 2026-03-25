import unittest
from datetime import UTC, datetime

from fastapi import HTTPException, Response
from pydantic import ValidationError
from starlette.datastructures import FormData, UploadFile

from app.api.v1.chat.api import chat, deliver, get_agent, get_session_detail, list_sessions, upload_attachments
from app.api.v1.chat.schema import ChatRequest, DeliverRequest
from app.domain import (
    AgentState,
    Attachment,
    AttachmentKind,
    ChatResponse,
    SessionDetailResponse as DomainSessionDetailResponse,
    SessionHistoryAgentResponseEntry,
    SessionHistoryMessageEntry,
    SessionListItem,
    SessionListResponse as DomainSessionListResponse,
    Session,
    SessionStatus,
    TranscriptionStatus,
    User,
    WaitingFor,
)
from app.services.attachments.storage import AttachmentValidationError


class FakeRequest:
    def __init__(self, form_data: FormData) -> None:
        self._form_data = form_data

    async def form(self) -> FormData:
        return self._form_data


class StubConversationContextService:
    def ensure_default_user(self) -> User:
        return User(
            id="user-123",
            name="Default User",
            api_key_hash=None,
            created_at=datetime.now(UTC),
        )

    def load_or_create_session(self, session_id: str | None, user: User) -> Session:
        del user
        resolved_session_id = session_id or "sess-created"
        timestamp = datetime.now(UTC)
        return Session(
            id=resolved_session_id,
            user_id="user-123",
            root_agent_id=None,
            status=SessionStatus.ACTIVE,
            summary=None,
            created_at=timestamp,
            updated_at=timestamp,
        )


class StubAttachmentApiService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.last_session_id: str | None = None
        self.last_source: str | None = None
        self.last_filenames: list[str] = []

    async def ingest_uploads(self, *, session_id: str, uploads: list[UploadFile], source: str | None = None) -> list[Attachment]:
        if self.error is not None:
            raise self.error

        self.last_session_id = session_id
        self.last_source = source
        self.last_filenames = [str(upload.filename) for upload in uploads]
        timestamp = datetime.now(UTC)
        return [
            Attachment(
                id="att-123",
                session_id=session_id,
                agent_id=None,
                item_id=None,
                kind=AttachmentKind.AUDIO,
                mime_type="audio/webm",
                original_filename=self.last_filenames[0],
                stored_filename="20260323_101530_voice-message.webm",
                workspace_path=f"input/{session_id}/20260323_101530_voice-message.webm",
                size_bytes=182340,
                source=source,
                transcription_status=TranscriptionStatus.COMPLETED,
                transcription_text="Przygotuj podsumowanie tego nagrania.",
                created_at=timestamp,
            )
        ]


class StubChatApiService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[object] = []

    async def process_chat(self, request: object) -> ChatResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error

        timestamp = datetime.now(UTC)
        attachment = Attachment(
            id="att-123",
            session_id="sess-123",
            agent_id="agent-123",
            item_id="item-123",
            kind=AttachmentKind.DOCUMENT,
            mime_type="text/plain",
            original_filename="note.txt",
            stored_filename="20260323_note.txt",
            workspace_path="input/sess-123/20260323_note.txt",
            size_bytes=4,
            source="file_picker",
            transcription_status=TranscriptionStatus.NOT_APPLICABLE,
            transcription_text=None,
            created_at=timestamp,
        )
        return ChatResponse(
            user_id="user-123",
            session_id="sess-123",
            agent_id="agent-123",
            model="gpt-test",
            status="completed",
            output=[
                {"type": "function_call", "callId": "call-1", "name": "delegate", "arguments": {"agent": "azazel"}},
                {
                    "type": "function_call_output",
                    "callId": "call-1",
                    "name": "delegate",
                    "output": "Child finished",
                    "isError": False,
                },
                {"type": "text", "text": "OK"},
            ],
            attachments=[attachment],
            error=None,
        )

    def get_agent_state(self, agent_id: str) -> AgentState:
        return AgentState(
            agent_id=agent_id,
            session_id="sess-123",
            root_agent_id="agent-123",
            parent_id=None,
            source_call_id=None,
            model="gpt-test",
            status="waiting",
            depth=0,
            turn_count=2,
            waiting_for=[],
            result=None,
            error=None,
        )

    async def deliver_result(self, *, agent_id: str, call_id: str, output: object, is_error: bool) -> AgentState:
        del call_id, output, is_error
        return AgentState(
            agent_id=agent_id,
            session_id="sess-123",
            root_agent_id="agent-123",
            parent_id=None,
            source_call_id=None,
            model="gpt-test",
            status="completed",
            depth=0,
            turn_count=3,
            waiting_for=[],
            result="Done",
            error=None,
        )


class StubSessionHistoryApiService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error

    def list_sessions(self, user_id: str) -> DomainSessionListResponse:
        del user_id
        timestamp = datetime.now(UTC)
        return DomainSessionListResponse(
            sessions=[
                SessionListItem(
                    id="sess-123",
                    root_agent_id="agent-123",
                    status=SessionStatus.ACTIVE,
                    summary="Popraw parser PDF",
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            ]
        )

    def get_session_detail(self, user_id: str, session_id: str) -> DomainSessionDetailResponse:
        del user_id
        if self.error is not None:
            raise self.error

        timestamp = datetime.now(UTC)
        return DomainSessionDetailResponse(
            session_id=session_id,
            root_agent_id="agent-123",
            status=SessionStatus.ACTIVE,
            summary="Popraw parser PDF",
            created_at=timestamp,
            updated_at=timestamp,
            entries=[
                SessionHistoryMessageEntry(
                    item_id="item-1",
                    message="Hej",
                    created_at=timestamp,
                    attachments=[],
                ),
                SessionHistoryAgentResponseEntry(
                    agent_id="agent-123",
                    model="gpt-test",
                    status="waiting",
                    created_at=timestamp,
                    output=[{"type": "text", "text": "Pracuje nad tym"}],
                    waiting_for=[
                        WaitingFor(
                            call_id="call-1",
                            type="agent",
                            name="delegate",
                            description="Waiting for child agent.",
                            agent_id="agent-child",
                        )
                    ],
                    attachments=[],
                    error=None,
                ),
            ],
        )


class ChatApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_upload_endpoint_returns_session_and_attachment_payload(self) -> None:
        file_upload = UploadFile(filename="voice-message.webm", file=None, headers={"content-type": "audio/webm"})
        request = FakeRequest(
            FormData(
                [
                    ("source", "voice_recording"),
                    ("files", file_upload),
                ]
            )
        )
        attachment_service = StubAttachmentApiService()
        conversation_context = StubConversationContextService()

        response = await upload_attachments(
            request=request,
            attachment_service=attachment_service,
            conversation_context=conversation_context,
        )

        self.assertEqual(response.session_id, "sess-created")
        self.assertEqual(response.attachments[0].kind, "audio")
        self.assertEqual(
            response.attachments[0].workspace_path,
            "input/sess-created/20260323_101530_voice-message.webm",
        )
        self.assertEqual(attachment_service.last_session_id, "sess-created")
        self.assertEqual(attachment_service.last_source, "voice_recording")
        self.assertEqual(attachment_service.last_filenames, ["voice-message.webm"])

    async def test_upload_endpoint_rejects_invalid_source(self) -> None:
        request = FakeRequest(FormData([("source", "unknown"), ("files", UploadFile(filename="x.txt", file=None))]))

        with self.assertRaises(HTTPException) as captured:
            await upload_attachments(
                request=request,
                attachment_service=StubAttachmentApiService(),
                conversation_context=StubConversationContextService(),
            )

        self.assertEqual(captured.exception.status_code, 422)

    async def test_chat_schema_rejects_empty_message_without_attachments(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest.model_validate({"message": "   ", "attachmentIds": []})

    async def test_chat_endpoint_maps_attachment_validation_error_to_bad_request(self) -> None:
        payload = ChatRequest.model_validate(
            {"message": "Przeanalizuj to.", "sessionId": "sess-123", "attachmentIds": ["att-999"]}
        )

        with self.assertRaises(HTTPException) as captured:
            await chat(
                payload=payload,
                http_response=Response(),
                chat_service=StubChatApiService(
                    error=AttachmentValidationError("Attachment att-999 does not belong to session sess-123.")
                ),
            )

        self.assertEqual(captured.exception.status_code, 400)

    async def test_chat_endpoint_returns_attachment_payloads(self) -> None:
        payload = ChatRequest.model_validate({"message": "Przeanalizuj to."})

        response = await chat(
            payload=payload,
            http_response=Response(),
            chat_service=StubChatApiService(),
        )

        self.assertEqual(response.status, "completed")
        self.assertEqual(response.attachments[0].workspace_path, "input/sess-123/20260323_note.txt")
        self.assertEqual(response.output[1].type, "function_call_output")
        self.assertEqual(response.output[1].call_id, "call-1")
        self.assertEqual(response.output[1].output, "Child finished")

    async def test_get_agent_endpoint_returns_state_payload(self) -> None:
        response = await get_agent(agent_id="agent-123", chat_service=StubChatApiService())

        self.assertEqual(response.agent_id, "agent-123")
        self.assertEqual(response.status, "waiting")

    async def test_deliver_endpoint_returns_agent_state_payload(self) -> None:
        response = await deliver(
            agent_id="agent-123",
            payload=DeliverRequest.model_validate({"callId": "call-1", "output": "OK"}),
            http_response=Response(),
            chat_service=StubChatApiService(),
        )

        self.assertEqual(response.agent_id, "agent-123")
        self.assertEqual(response.status, "completed")

    async def test_list_sessions_endpoint_returns_session_list_payload(self) -> None:
        response = await list_sessions(
            session_history_service=StubSessionHistoryApiService(),
            conversation_context=StubConversationContextService(),
        )

        self.assertEqual(response.sessions[0].id, "sess-123")
        self.assertEqual(response.sessions[0].root_agent_id, "agent-123")
        self.assertEqual(response.sessions[0].summary, "Popraw parser PDF")

    async def test_get_session_detail_endpoint_returns_history_payload(self) -> None:
        response = await get_session_detail(
            session_id="sess-123",
            session_history_service=StubSessionHistoryApiService(),
            conversation_context=StubConversationContextService(),
        )

        self.assertEqual(response.session_id, "sess-123")
        self.assertEqual(response.entries[0].type, "message")
        self.assertEqual(response.entries[1].type, "agent_response")
        self.assertEqual(response.entries[1].status, "waiting")
        self.assertEqual(response.entries[1].waiting_for[0].call_id, "call-1")

    async def test_get_session_detail_endpoint_returns_404_for_missing_session(self) -> None:
        with self.assertRaises(HTTPException) as captured:
            await get_session_detail(
                session_id="sess-missing",
                session_history_service=StubSessionHistoryApiService(
                    error=LookupError("Session sess-missing does not exist.")
                ),
                conversation_context=StubConversationContextService(),
            )

        self.assertEqual(captured.exception.status_code, 404)
