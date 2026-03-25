import json
from collections import defaultdict

from app.db.repositories.agent_repository import AgentRepository
from app.db.repositories.attachment_repository import AttachmentRepository
from app.db.repositories.item_repository import ItemRepository
from app.db.repositories.session_repository import SessionRepository
from app.domain import (
    Agent,
    Attachment,
    ChatFunctionCallOutput,
    ChatFunctionResultOutput,
    ChatOutputItem,
    ChatTextOutput,
    Item,
    ItemType,
    MessageRole,
    Session,
    SessionDetailResponse,
    SessionHistoryAgentResponseEntry,
    SessionHistoryEntry,
    SessionHistoryMessageEntry,
    SessionListItem,
    SessionListResponse,
)


class SessionHistoryService:
    def __init__(
        self,
        *,
        session_repository: SessionRepository,
        agent_repository: AgentRepository,
        item_repository: ItemRepository,
        attachment_repository: AttachmentRepository,
    ) -> None:
        self._session_repository = session_repository
        self._agent_repository = agent_repository
        self._item_repository = item_repository
        self._attachment_repository = attachment_repository

    def list_sessions(self, user_id: str) -> SessionListResponse:
        sessions = sorted(
            self._session_repository.list_by_user(user_id),
            key=lambda session: (session.updated_at, session.created_at),
            reverse=True,
        )
        return SessionListResponse(
            sessions=[
                SessionListItem(
                    id=session.id,
                    root_agent_id=session.root_agent_id,
                    status=session.status,
                    summary=self._resolve_summary(session, self._item_repository.list_by_session(session.id)),
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                )
                for session in sessions
            ]
        )

    def get_session_detail(self, user_id: str, session_id: str) -> SessionDetailResponse:
        session = self._session_repository.get_by_id(session_id)
        if session is None or session.user_id != user_id:
            raise LookupError(f"Session {session_id} does not exist.")

        agents = self._agent_repository.list_by_session(session_id)
        items = self._item_repository.list_by_session(session_id)
        attachments = self._attachment_repository.list_by_session(session_id)

        return SessionDetailResponse(
            session_id=session.id,
            root_agent_id=session.root_agent_id,
            status=session.status,
            summary=self._resolve_summary(session, items),
            created_at=session.created_at,
            updated_at=session.updated_at,
            entries=self._build_entries(
                session=session,
                agents=agents,
                items=items,
                attachments=attachments,
            ),
        )

    def _build_entries(
        self,
        *,
        session: Session,
        agents: list[Agent],
        items: list[Item],
        attachments: list[Attachment],
    ) -> list[SessionHistoryEntry]:
        agents_by_id = {agent.id: agent for agent in agents}
        attachments_by_item = defaultdict(list)
        for attachment in attachments:
            if attachment.item_id is not None:
                attachments_by_item[attachment.item_id].append(attachment)

        root_agent_id = session.root_agent_id or (items[0].agent_id if items else None)
        if root_agent_id is None:
            return []

        root_agent = agents_by_id.get(root_agent_id)
        root_items = sorted(
            (item for item in items if item.agent_id == root_agent_id),
            key=lambda item: (item.sequence, item.created_at),
        )

        entries: list[SessionHistoryEntry] = []
        current_message: Item | None = None
        response_items: list[Item] = []

        for item in root_items:
            if item.type == ItemType.MESSAGE and item.role == MessageRole.USER:
                if current_message is not None:
                    entries.append(
                        self._build_agent_response_entry(
                            agent=root_agent,
                            message_item=current_message,
                            response_items=response_items,
                            attachments_by_item=attachments_by_item,
                            is_last_turn=False,
                        )
                    )
                entries.append(
                    SessionHistoryMessageEntry(
                        item_id=item.id,
                        message=item.content or "",
                        created_at=item.created_at,
                        attachments=list(attachments_by_item.get(item.id, [])),
                    )
                )
                current_message = item
                response_items = []
                continue

            if current_message is not None:
                response_items.append(item)

        if current_message is not None:
            entries.append(
                self._build_agent_response_entry(
                    agent=root_agent,
                    message_item=current_message,
                    response_items=response_items,
                    attachments_by_item=attachments_by_item,
                    is_last_turn=True,
                )
            )

        return entries

    def _build_agent_response_entry(
        self,
        *,
        agent: Agent | None,
        message_item: Item,
        response_items: list[Item],
        attachments_by_item: dict[str, list[Attachment]],
        is_last_turn: bool,
    ) -> SessionHistoryAgentResponseEntry:
        output = self._serialize_output(response_items)
        attachments: list[Attachment] = []
        for item in response_items:
            attachments.extend(attachments_by_item.get(item.id, []))

        status = "completed"
        waiting_for = []
        error = None
        model = ""
        agent_id = message_item.agent_id
        if agent is not None:
            agent_id = agent.id
            model = agent.config.model
            if is_last_turn:
                if agent.status.value in {"failed", "cancelled"}:
                    status = "failed"
                    error = agent.error
                elif agent.status.value in {"waiting", "pending", "running"}:
                    status = "waiting"
                    waiting_for = list(agent.waiting_for)

        created_at = response_items[0].created_at if response_items else message_item.created_at
        return SessionHistoryAgentResponseEntry(
            agent_id=agent_id,
            model=model,
            status=status,
            created_at=created_at,
            output=output,
            waiting_for=waiting_for,
            attachments=attachments,
            error=error,
        )

    def _resolve_summary(self, session: Session, items: list[Item]) -> str:
        if session.summary and session.summary.strip():
            return session.summary.strip()

        first_message = next(
            (
                item.content
                for item in items
                if item.type == ItemType.MESSAGE
                and item.role == MessageRole.USER
                and item.content
                and (
                    session.root_agent_id is None
                    or item.agent_id == session.root_agent_id
                )
            ),
            None,
        )
        if first_message is None:
            return ""

        normalized = " ".join(line.strip() for line in first_message.splitlines() if line.strip())
        return normalized[:117] + "..." if len(normalized) > 120 else normalized

    def _serialize_output(self, items: list[Item]) -> list[ChatOutputItem]:
        output: list[ChatOutputItem] = []

        for item in items:
            if item.type == ItemType.MESSAGE and item.role == MessageRole.ASSISTANT and item.content:
                output.append(self._serialize_text_output(item.content))
                continue

            if item.type == ItemType.FUNCTION_CALL and item.call_id and item.name:
                output.append(
                    self._serialize_function_call_output(
                        call_id=item.call_id,
                        name=item.name,
                        arguments=self._parse_arguments(item.arguments_json),
                    )
                )
                continue

            if item.type == ItemType.FUNCTION_CALL_OUTPUT and item.call_id and item.name and item.output is not None:
                output.append(
                    self._serialize_function_result_output(
                        call_id=item.call_id,
                        name=item.name,
                        output=self._parse_output(item.output),
                        is_error=item.is_error,
                    )
                )

        return output

    @staticmethod
    def _serialize_text_output(text: str) -> ChatTextOutput:
        return {
            "type": "text",
            "text": text,
        }

    @staticmethod
    def _serialize_function_call_output(
        *,
        call_id: str,
        name: str,
        arguments: dict[str, object],
    ) -> ChatFunctionCallOutput:
        return {
            "type": "function_call",
            "callId": call_id,
            "name": name,
            "arguments": arguments,
        }

    @staticmethod
    def _serialize_function_result_output(
        *,
        call_id: str,
        name: str,
        output: object,
        is_error: bool,
    ) -> ChatFunctionResultOutput:
        return {
            "type": "function_call_output",
            "callId": call_id,
            "name": name,
            "output": output,
            "isError": is_error,
        }

    @staticmethod
    def _parse_arguments(arguments_json: str | None) -> dict[str, object]:
        if arguments_json is None:
            return {}

        try:
            parsed = json.loads(arguments_json)
        except json.JSONDecodeError:
            return {}

        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _parse_output(output: str) -> object:
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return output
