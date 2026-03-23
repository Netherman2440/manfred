import json

from app.db.repositories.item_repository import ItemRepository
from app.domain import (
    Agent,
    AgentConfig,
    Attachment,
    ChatFunctionCallOutput,
    ChatOutputItem,
    ChatRequest,
    ChatResponse,
    ChatTextOutput,
    ChatTurn,
    FunctionToolDefinition,
    Item,
    ItemType,
    MessageRole,
    ToolRegistry,
)
from app.runtime import AgentRunner
from app.services.attachments import AttachmentService, ChatInputBuilder
from app.services.conversation_context import ConversationContextService
from app.services.observability import ObservabilityService


class ChatValidationError(ValueError):
    pass


class ChatService:
    def __init__(
        self,
        *,
        item_repository: ItemRepository,
        attachment_service: AttachmentService,
        agent_config: AgentConfig,
        tool_registry: ToolRegistry,
        agent_runner: AgentRunner,
        observability: ObservabilityService,
        chat_input_builder: ChatInputBuilder,
        conversation_context: ConversationContextService,
    ) -> None:
        self._item_repository = item_repository
        self._attachment_service = attachment_service
        self._agent_config = agent_config
        self._tool_registry = tool_registry
        self._agent_runner = agent_runner
        self._observability = observability
        self._chat_input_builder = chat_input_builder
        self._conversation_context = conversation_context

    async def prepare_chat_turn(self, request: ChatRequest) -> ChatTurn:
        user = self._conversation_context.ensure_default_user()
        session = self._conversation_context.load_or_create_session(request.session_id, user)
        tools = self._resolve_tools(self._agent_config.tool_names)
        agent = self._conversation_context.load_or_create_root_agent(session, self._agent_config)
        attachments = self._attachment_service.get_for_session(
            session_id=session.id,
            attachment_ids=request.attachment_ids,
        )
        attachments = await self._attachment_service.ensure_transcriptions(attachments)
        user_input = self._chat_input_builder.build(message=request.message, attachments=attachments)
        if user_input.strip() == "":
            raise ChatValidationError("message must not be empty when no attachments are provided.")

        trace_id = self._observability.create_trace_id()
        response_start_sequence = self._item_repository.get_last_sequence(agent.id)
        user_item = self._create_user_message_item(session.id, agent.id, user_input, response_start_sequence + 1)
        assigned_attachments = self._attachment_service.assign_to_item(
            attachments,
            agent_id=agent.id,
            item_id=user_item.id,
        )

        return ChatTurn(
            user=user,
            session=session,
            agent=agent,
            user_item=user_item,
            trace_id=trace_id,
            response_start_sequence=response_start_sequence,
            attachments=assigned_attachments,
            tools=tools,
        )

    async def process_chat(self, request: ChatRequest) -> ChatResponse:
        chat_turn = await self.prepare_chat_turn(request)
        with self._observability.start_chat_turn(
            trace_id=chat_turn.trace_id,
            session_id=chat_turn.session.id,
            user_id=chat_turn.user.id,
            agent_id=chat_turn.agent.id,
            message=chat_turn.user_item.content or "",
            attachments=self._serialize_attachments(chat_turn.attachments),
        ):
            self._observability.record_item(chat_turn.user_item)

            try:
                run_result = await self._agent_runner.run_agent(chat_turn.agent.id)
                items = self._item_repository.list_by_agent(chat_turn.agent.id)
                visible_items = self._filter_response_items(items, chat_turn.response_start_sequence)
                response = self._to_chat_response(chat_turn, run_result.agent, visible_items, error=run_result.error)
            except Exception as exc:
                error_message = str(exc) or "Chat processing failed."
                self._observability.update_current_span(
                    level="ERROR",
                    status_message=error_message,
                )
                self._observability.record_error(
                    name="chat.turn.failed",
                    error=error_message,
                    metadata={"agent_id": chat_turn.agent.id, "session_id": chat_turn.session.id},
                )
                raise

            self._observability.update_current_span(
                output=self._serialize_response_for_observability(response),
                metadata={
                    "status": response.status,
                    "item_count": len(visible_items),
                },
                level="ERROR" if response.status == "failed" else None,
                status_message=response.error,
            )
            self._observability.flush()
            return response

    def _create_user_message_item(
        self,
        session_id: str,
        agent_id: str,
        message: str,
        sequence: int,
    ) -> Item:
        return self._item_repository.create(
            session_id=session_id,
            agent_id=agent_id,
            sequence=sequence,
            item_type=ItemType.MESSAGE,
            role=MessageRole.USER,
            content=message,
        )

    def _resolve_tools(self, tool_names: tuple[str, ...]) -> list[FunctionToolDefinition]:
        return self._tool_registry.list_by_name(tool_names)

    @staticmethod
    def _filter_response_items(items: list[Item], response_start_sequence: int) -> list[Item]:
        return [item for item in items if item.sequence > response_start_sequence]

    def _to_chat_response(
        self,
        chat_turn: ChatTurn,
        agent: Agent,
        items: list[Item],
        *,
        error: str | None,
    ) -> ChatResponse:
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

        status = "failed" if error is not None or agent.status.value == "failed" else "completed"
        return ChatResponse(
            user_id=chat_turn.user.id,
            session_id=chat_turn.session.id,
            agent_id=agent.id,
            model=agent.config.model,
            status=status,
            output=output,
            attachments=chat_turn.attachments,
            error=error,
        )

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
    def _parse_arguments(arguments_json: str | None) -> dict[str, object]:
        if arguments_json is None:
            return {}

        try:
            parsed = json.loads(arguments_json)
        except json.JSONDecodeError:
            return {}

        if isinstance(parsed, dict):
            return parsed
        return {}

    @staticmethod
    def _serialize_response_for_observability(response: ChatResponse) -> dict[str, object]:
        return {
            "session_id": response.session_id,
            "agent_id": response.agent_id,
            "model": response.model,
            "status": response.status,
            "error": response.error,
            "output": response.output,
            "attachments": ChatService._serialize_attachments(response.attachments),
        }

    @staticmethod
    def _serialize_attachments(attachments: list[Attachment]) -> list[dict[str, object]]:
        return [
            {
                "id": attachment.id,
                "kind": attachment.kind.value,
                "mime_type": attachment.mime_type,
                "workspace_path": attachment.workspace_path,
                "transcription_status": attachment.transcription_status.value,
            }
            for attachment in attachments
        ]
