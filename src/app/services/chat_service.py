import json
import uuid

from app.db.repositories.agent_repository import AgentRepository
from app.db.repositories.item_repository import ItemRepository
from app.db.repositories.session_repository import SessionRepository
from app.db.repositories.user_repository import UserRepository
from app.domain import (
    Agent,
    AgentConfig,
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
    Session,
    ToolRegistry,
    User,
    prepare_agent_for_next_turn,
)
from app.runtime import AgentRunner


class ChatService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        session_repository: SessionRepository,
        agent_repository: AgentRepository,
        item_repository: ItemRepository,
        agent_config: AgentConfig,
        tool_registry: ToolRegistry,
        agent_runner: AgentRunner,
        default_user_id: str,
        default_user_name: str,
    ) -> None:
        self._user_repository = user_repository
        self._session_repository = session_repository
        self._agent_repository = agent_repository
        self._item_repository = item_repository
        self._agent_config = agent_config
        self._tool_registry = tool_registry
        self._agent_runner = agent_runner
        self._default_user_id = default_user_id
        self._default_user_name = default_user_name

    def prepare_chat_turn(self, request: ChatRequest) -> ChatTurn:
        # TODO: Resolve the local user from auth instead of the default bootstrap user.
        user = self._ensure_default_user()
        session = self._load_session(request.session_id, user)
        tools = self._resolve_tools(self._agent_config.tool_names)
        agent = self._load_or_create_root_agent(session)
        trace_id = str(uuid.uuid4())
        response_start_sequence = self._item_repository.get_last_sequence(agent.id)
        user_item = self._create_user_message_item(session, agent, request.message, response_start_sequence + 1)

        return ChatTurn(
            user=user,
            session=session,
            agent=agent,
            user_item=user_item,
            trace_id=trace_id,
            response_start_sequence=response_start_sequence,
            tools=tools,
        )

    async def process_chat(self, request: ChatRequest) -> ChatResponse:

        chat_turn = self.prepare_chat_turn(request)

        run_result = await self._agent_runner.run_agent(chat_turn.agent.id)

        items = self._item_repository.list_by_agent(chat_turn.agent.id)

        visible_items = self._filter_response_items(items, chat_turn.response_start_sequence)

        return self._to_chat_response(chat_turn, run_result.agent, visible_items, error=run_result.error)


    def _ensure_default_user(self) -> User:
        user = self._user_repository.get_by_id(self._default_user_id)
        if user is not None:
            return user

        return self._user_repository.create(
            name=self._default_user_name,
            user_id=self._default_user_id,
        )

    def _load_session(self, session_id: str | None, user: User) -> Session:
        if session_id:
            session = self._session_repository.get_by_id(session_id)
            if session is not None:
                return session

        return self._session_repository.create(user_id=user.id)

    def _load_or_create_root_agent(self, session: Session) -> Agent:
        if session.root_agent_id:
            agent = self._agent_repository.get_by_id(session.root_agent_id)
            if agent is not None:
                prepared_agent = prepare_agent_for_next_turn(agent, config=self._agent_config)
                return self._agent_repository.update(prepared_agent)

        agent = self._agent_repository.create(
            session_id=session.id,
            config=self._agent_config,
        )

        updated_session = Session(
            id=session.id,
            user_id=session.user_id,
            root_agent_id=agent.id,
            status=session.status,
            summary=session.summary,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
        self._session_repository.update(updated_session)
        return agent

    def _create_user_message_item(
        self,
        session: Session,
        agent: Agent,
        message: str,
        sequence: int,
    ) -> Item:
        return self._item_repository.create(
            session_id=session.id,
            agent_id=agent.id,
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
