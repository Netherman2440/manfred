from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session as DbSession

from app.api.v1.chat.schema import (
    ChatAgentConfigInput,
    ChatRequest,
    ChatResponse,
    FunctionCallOutputItem,
    FunctionCallResultOutputItem,
    FunctionToolDefinitionInput,
    TextOutputItem,
    WebSearchToolDefinitionInput,
)
from app.config import Settings
from app.db.base import utcnow
from app.domain import (
    Agent,
    AgentConfig,
    AgentStatus,
    FunctionToolDefinition,
    Item,
    ItemType,
    MessageRole,
    Session,
    SessionStatus,
    ToolDefinition,
    User,
    WebSearchToolDefinition,
)
from app.domain.repositories import AgentRepository, ItemRepository, SessionRepository, UserRepository
from app.runtime.runner import Runner
from app.services.agent_loader import AgentLoader
from app.providers import ProviderErrorEvent, ProviderStreamEvent


class ChatServiceValidationError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class ResolvedAgentConfig:
    agent_name: str
    model: str
    task: str
    tools: list[ToolDefinition]
    temperature: float | None


@dataclass(slots=True, frozen=True)
class PreparedChatSetup:
    session: Session
    agent: Agent
    last_sequence: int


@dataclass(slots=True, frozen=True)
class PreparedChatSetupResult:
    ok: bool
    value: PreparedChatSetup | None = None
    error: str | None = None


class ChatService:
    def __init__(
        self,
        *,
        session: DbSession,
        settings: Settings,
        agent_loader: AgentLoader,
        user_repository: UserRepository,
        session_repository: SessionRepository,
        agent_repository: AgentRepository,
        item_repository: ItemRepository,
        runner: Runner,
    ) -> None:
        self.session = session
        self.settings = settings
        self.agent_loader = agent_loader
        self.user_repository = user_repository
        self.session_repository = session_repository
        self.agent_repository = agent_repository
        self.item_repository = item_repository
        self.runner = runner

    async def process_chat(self, chat_request: ChatRequest) -> ChatResponse:
        try:
            setup = await self.prepare_chat(chat_request)
            if not setup.ok or setup.value is None:
                raise ChatServiceValidationError(setup.error or "Chat setup failed.")

            self.session.flush()
            response = await self.execute_chat(
                setup.value.agent.id,
                setup.value.last_sequence,
                include_tool_result=chat_request.include_tool_result,
            )
            self.session.commit()
            return response
        except ChatServiceValidationError:
            self.session.rollback()
            raise
        except Exception:
            self.session.rollback()
            raise

    async def process_chat_stream(self, chat_request: ChatRequest) -> AsyncIterable[ProviderStreamEvent]:
        try:
            setup = await self.prepare_chat(chat_request)
            if not setup.ok or setup.value is None:
                yield ProviderErrorEvent(error=setup.error or "Chat setup failed.")
                return

            self.session.flush()
            async for event in self.stream_prepared_chat(setup.value):
                yield event
            self.session.commit()
        except asyncio.CancelledError:
            self.session.rollback()
            raise
        except Exception as exc:
            self.session.rollback()
            yield ProviderErrorEvent(error=str(exc) or "Chat streaming failed.")

    async def prepare_chat(self, chat_request: ChatRequest) -> PreparedChatSetupResult:
        try:
            user = self._ensure_default_user() #TODO: Get real user
            session = self._load_session(chat_request.session_id, user.id)
            resolved_config = self._resolve_agent_config(chat_request.agent_config)
            agent = self._resolve_session_root_agent(session, resolved_config)
            last_sequence = self.item_repository.get_last_sequence(agent.id)
            self._store_input_items(chat_request, session, agent, last_sequence)
        except ChatServiceValidationError as exc:
            return PreparedChatSetupResult(ok=False, error=str(exc))

        return PreparedChatSetupResult(
            ok=True,
            value=PreparedChatSetup(
                session=session,
                agent=agent,
                last_sequence=last_sequence,
            ),
        )

    async def stream_prepared_chat(
        self,
        setup: PreparedChatSetup,
    ) -> AsyncIterable[ProviderStreamEvent]:
        async for event in self.runner.run_agent_stream(
            setup.agent.id,
            last_agent_sequence=setup.last_sequence,
        ):
            yield event

    async def execute_chat(
        self,
        agent_id: str,
        last_sequence: int,
        *,
        include_tool_result: bool = False,
    ) -> ChatResponse:
        result = await self.runner.run_agent(agent_id, last_agent_sequence=last_sequence)
        agent = result.agent or self.agent_repository.get(agent_id)
        if agent is None:
            raise RuntimeError(f"Agent disappeared during execution: {agent_id}")

        response_items = self.item_repository.list_by_agent_after_sequence(agent_id, last_sequence)
        output = self._build_response_output(
            response_items,
            include_tool_result=include_tool_result,
        )

        return ChatResponse(
            id=agent.id,
            session_id=agent.session_id,
            status=result.status,
            model=agent.config.model,
            output=output,
            error=result.error,
        )

    def close(self) -> None:
        self.session.close()

    def _ensure_default_user(self) -> User:
        user = self.user_repository.get(self.settings.DEFAULT_USER_ID)
        if user is not None:
            return user

        user = User(
            id=self.settings.DEFAULT_USER_ID,
            name=self.settings.DEFAULT_USER_NAME,
            api_key_hash=None,
            created_at=utcnow(),
        )
        return self.user_repository.save(user)

    def _load_session(self, session_id: str | None, user_id: str) -> Session:
        if not session_id:
            now = utcnow()
            session = Session(
                id=uuid4().hex,
                user_id=user_id,
                root_agent_id=None,
                status=SessionStatus.ACTIVE,
                title=None,
                created_at=now,
                updated_at=now,
            )
            return self.session_repository.save(session)

        session = self.session_repository.get(session_id)
        if session is None:
            raise ChatServiceValidationError(f"Session not found: {session_id}")
        return session

    def _resolve_agent_config(self, request_config: ChatAgentConfigInput | None) -> ResolvedAgentConfig:
        loaded_agent = self.agent_loader.load_agent(self.settings.DEFAULT_AGENT)
        default_model = f"openrouter:{self.settings.OPEN_ROUTER_LLM_MODEL}"
        base_config = ResolvedAgentConfig(
            agent_name=loaded_agent.agent_name,
            model=loaded_agent.model or default_model,
            task=loaded_agent.system_prompt or "You are Manfred, a helpful assistant.",
            tools=list(loaded_agent.tools),
            temperature=None,
        )
        if request_config is None:
            return base_config

        return ResolvedAgentConfig(
            agent_name=base_config.agent_name,
            model=request_config.model or base_config.model,
            task=request_config.task or base_config.task,
            tools=self._resolve_tools(request_config.tools) if request_config.tools is not None else base_config.tools,
            temperature=request_config.temperature if request_config.temperature is not None else base_config.temperature,
        )

    def _resolve_tools(
        self,
        tools: list[FunctionToolDefinitionInput | WebSearchToolDefinitionInput],
    ) -> list[ToolDefinition]:
        resolved: list[ToolDefinition] = []
        for tool in tools:
            if isinstance(tool, FunctionToolDefinitionInput):
                resolved.append(
                    FunctionToolDefinition(
                        name=tool.name,
                        description=tool.description,
                        parameters=tool.parameters,
                    )
                )
                continue

            if isinstance(tool, WebSearchToolDefinitionInput):
                resolved.append(WebSearchToolDefinition())

        return resolved

    def _resolve_session_root_agent(self, session: Session, config: ResolvedAgentConfig) -> Agent:
        agent_config = AgentConfig(
            model=config.model,
            task=config.task,
            tools=config.tools,
            temperature=config.temperature,
        )
        now = utcnow()

        if session.root_agent_id is not None:
            agent = self.agent_repository.get(session.root_agent_id)
            if agent is None:
                raise RuntimeError(f"Session integrity error: root agent not found: {session.root_agent_id}")

            agent.agent_name = config.agent_name
            agent.config = agent_config
            agent.status = AgentStatus.PENDING
            agent.updated_at = now
            return self.agent_repository.save(agent)

        agent_id = uuid4().hex
        agent = Agent(
            id=agent_id,
            session_id=session.id,
            root_agent_id=agent_id,
            parent_id=None,
            depth=0,
            agent_name=config.agent_name,
            status=AgentStatus.PENDING,
            turn_count=0,
            config=agent_config,
            created_at=now,
            updated_at=now,
        )
        saved_agent = self.agent_repository.save(agent)
        session.root_agent_id = saved_agent.id
        session.updated_at = now
        self.session_repository.save(session)
        return saved_agent

    def _store_input_items(
        self,
        chat_request: ChatRequest,
        session: Session,
        agent: Agent,
        last_sequence: int,
    ) -> None:
        sequence = last_sequence
        for input_item in chat_request.input:
            if input_item.type != "message":
                continue

            sequence += 1
            item = Item(
                id=uuid4().hex,
                session_id=session.id,
                agent_id=agent.id,
                sequence=sequence,
                type=ItemType.MESSAGE,
                role=MessageRole(input_item.role),
                content=input_item.content,
                call_id=None,
                name=None,
                arguments_json=None,
                output=None,
                is_error=False,
                created_at=utcnow(),
            )
            self.item_repository.save(item)

    @staticmethod
    def _build_response_output(
        items: list[Item],
        *,
        include_tool_result: bool = False,
    ) -> list[TextOutputItem | FunctionCallOutputItem | FunctionCallResultOutputItem]:
        output: list[TextOutputItem | FunctionCallOutputItem | FunctionCallResultOutputItem] = []

        for item in items:
            if item.type == ItemType.MESSAGE and item.role == MessageRole.ASSISTANT and item.content:
                output.append(TextOutputItem(text=item.content))
                continue

            if item.type == ItemType.FUNCTION_CALL:
                output.append(
                    FunctionCallOutputItem(
                        call_id=item.call_id or "",
                        name=item.name or "",
                        arguments=ChatService._deserialize_arguments(item.arguments_json),
                    )
                )
                continue

            if include_tool_result and item.type == ItemType.FUNCTION_CALL_OUTPUT:
                tool_result = ChatService._deserialize_tool_result(item.output)
                output.append(
                    FunctionCallResultOutputItem(
                        call_id=item.call_id or "",
                        name=item.name or "",
                        output=ChatService._extract_tool_result_output(tool_result),
                        is_error=item.is_error,
                    )
                )

        return output

    @staticmethod
    def _deserialize_arguments(raw_arguments: str | None) -> dict[str, Any]:
        if not raw_arguments:
            return {}
        try:
            payload = json.loads(raw_arguments)
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _deserialize_tool_result(raw_output: str | None) -> dict[str, Any]:
        if not raw_output:
            return {}
        try:
            payload = json.loads(raw_output)
        except ValueError:
            return {"output": raw_output}
        if not isinstance(payload, dict):
            return {"output": raw_output}
        return payload

    @staticmethod
    def _extract_tool_result_output(result: dict[str, Any]) -> str | None:
        value = result.get("output")
        if value is None:
            value = result.get("error")
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=True)
