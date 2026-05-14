from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session as DbSession

from app.api.v1.chat.schema import (
    ChatAgentConfigInput,
    ChatEditRequest,
    ChatQueueRequest,
    ChatQueueResponse,
    ChatRequest,
    ChatResponse,
    ChatStreamSessionEvent,
    DeliverRequest,
    FunctionCallOutputItem,
    FunctionCallResultOutputItem,
    FunctionToolDefinitionInput,
    TextOutputItem,
    WaitingForOutputItem,
    WebSearchToolDefinitionInput,
)
from app.config import Settings
from app.db.base import utcnow
from app.domain import (
    Agent,
    AgentConfig,
    AgentStatus,
    Attachment,
    FunctionToolDefinition,
    Item,
    ItemType,
    MessageRole,
    QueuedInput,
    QueuedInputAttachment,
    Session,
    SessionStatus,
    ToolDefinition,
    User,
    WaitingForEntry,
    WebSearchToolDefinition,
)
from app.domain.repositories import (
    AgentRepository,
    ItemRepository,
    QueuedInputRepository,
    SessionRepository,
    UserRepository,
)
from app.providers import ProviderErrorEvent, ProviderStreamEvent
from app.runtime.cancellation import ActiveRunHandle, ActiveRunRegistry, CancellationSignal
from app.runtime.message_queue import SessionMessageQueue
from app.runtime.runner import Runner
from app.runtime.runner_types import RunResult
from app.services.agent_loader import AgentLoader
from app.services.chat_attachments import ChatAttachmentStorageService, IncomingAttachment, StoredAttachment
from app.services.filesystem import WorkspaceLayoutService


class ChatServiceValidationError(ValueError):
    pass


class ChatServiceNotFoundError(LookupError):
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
    existing_session_item_ids: set[str]


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
        queued_input_repository: QueuedInputRepository,
        runner: Runner,
        active_run_registry: ActiveRunRegistry,
        workspace_layout_service: WorkspaceLayoutService,
        attachment_storage_service: ChatAttachmentStorageService,
        message_queue: SessionMessageQueue,
    ) -> None:
        self.session = session
        self.settings = settings
        self.agent_loader = agent_loader
        self.user_repository = user_repository
        self.session_repository = session_repository
        self.agent_repository = agent_repository
        self.item_repository = item_repository
        self.queued_input_repository = queued_input_repository
        self.runner = runner
        self.active_run_registry = active_run_registry
        self.workspace_layout_service = workspace_layout_service
        self.attachment_storage_service = attachment_storage_service
        self.message_queue = message_queue

    async def process_chat(
        self,
        chat_request: ChatRequest,
        *,
        attachments: list[IncomingAttachment] | None = None,
    ) -> ChatResponse:
        active_run: ActiveRunHandle | None = None
        run_result: RunResult | None = None
        created_files: list[Path] = []
        try:
            setup, created_files = await self.prepare_chat(chat_request, attachments=attachments)
            if not setup.ok or setup.value is None:
                raise ChatServiceValidationError(setup.error or "Chat setup failed.")

            self.session.flush()
            active_run = await self.active_run_registry.start(setup.value.agent.id)
            response = await self.execute_chat(
                setup.value.agent.id,
                setup.value.last_sequence,
                existing_session_item_ids=setup.value.existing_session_item_ids,
                include_tool_result=chat_request.include_tool_result,
                signal=active_run.signal,
            )
            self.session.commit()
            agent = self.agent_repository.get(response.agent_id)
            if agent is not None:
                run_result = self.runner.build_run_result_from_agent(agent)
            return response
        except ChatServiceValidationError:
            self.session.rollback()
            self.attachment_storage_service.cleanup_files(created_files)
            raise
        except asyncio.CancelledError:
            self.session.rollback()
            self.attachment_storage_service.cleanup_files(created_files)
            if active_run is not None:
                run_result = self._build_cancelled_run_result(active_run.agent_id)
            raise
        except Exception as exc:
            self.session.rollback()
            self.attachment_storage_service.cleanup_files(created_files)
            if active_run is not None:
                run_result = self._build_failed_run_result(
                    active_run.agent_id,
                    str(exc) or "Chat execution failed.",
                )
            raise
        finally:
            if active_run is not None:
                await self.active_run_registry.finish(
                    active_run.agent_id,
                    run_result or self._build_failed_run_result(active_run.agent_id, "Chat execution failed."),
                )

    async def process_chat_stream(
        self,
        chat_request: ChatRequest,
        *,
        attachments: list[IncomingAttachment] | None = None,
    ) -> AsyncIterable[ProviderStreamEvent | ChatStreamSessionEvent]:
        active_run: ActiveRunHandle | None = None
        run_result: RunResult | None = None
        created_files: list[Path] = []
        try:
            setup, created_files = await self.prepare_chat(chat_request, attachments=attachments)
            if not setup.ok or setup.value is None:
                self.attachment_storage_service.cleanup_files(created_files)
                yield ProviderErrorEvent(error=setup.error or "Chat setup failed.")
                return

            self.session.flush()
            yield ChatStreamSessionEvent(
                session_id=setup.value.session.id,
                agent_id=setup.value.agent.id,
            )
            active_run = await self.active_run_registry.start(setup.value.agent.id)
            async for event in self.stream_prepared_chat(setup.value, signal=active_run.signal):
                yield event
            self.session.commit()
            agent = self.agent_repository.get(setup.value.agent.id)
            if agent is not None:
                run_result = self.runner.build_run_result_from_agent(agent)
        except asyncio.CancelledError:
            self.session.rollback()
            self.attachment_storage_service.cleanup_files(created_files)
            if active_run is not None:
                run_result = self._build_cancelled_run_result(active_run.agent_id)
            raise
        except Exception as exc:
            self.session.rollback()
            self.attachment_storage_service.cleanup_files(created_files)
            if active_run is not None:
                run_result = self._build_failed_run_result(
                    active_run.agent_id,
                    str(exc) or "Chat streaming failed.",
                )
            yield ProviderErrorEvent(error=str(exc) or "Chat streaming failed.")
        finally:
            if active_run is not None:
                await self.active_run_registry.finish(
                    active_run.agent_id,
                    run_result or self._build_failed_run_result(active_run.agent_id, "Chat streaming failed."),
                )

    async def process_edit(
        self,
        session_id: str,
        item_id: str,
        edit_request: ChatEditRequest,
        *,
        attachments: list[IncomingAttachment] | None = None,
        include_tool_result: bool = False,
    ) -> ChatResponse:
        active_run: ActiveRunHandle | None = None
        run_result: RunResult | None = None
        created_files: list[Path] = []
        try:
            response, created_files, active_run = await self._process_edit_internal(
                session_id,
                item_id,
                edit_request,
                attachments=attachments,
                include_tool_result=include_tool_result,
            )
            self.session.commit()
            agent = self.agent_repository.get(response.agent_id)
            if agent is not None:
                run_result = self.runner.build_run_result_from_agent(agent)
            return response
        except ChatServiceValidationError:
            self.session.rollback()
            self.attachment_storage_service.cleanup_files(created_files)
            raise
        except asyncio.CancelledError:
            self.session.rollback()
            self.attachment_storage_service.cleanup_files(created_files)
            if active_run is not None:
                run_result = self._build_cancelled_run_result(active_run.agent_id)
            raise
        except Exception as exc:
            self.session.rollback()
            self.attachment_storage_service.cleanup_files(created_files)
            if active_run is not None:
                run_result = self._build_failed_run_result(
                    active_run.agent_id,
                    str(exc) or "Chat edit failed.",
                )
            raise
        finally:
            if active_run is not None:
                await self.active_run_registry.finish(
                    active_run.agent_id,
                    run_result or self._build_failed_run_result(active_run.agent_id, "Chat edit failed."),
                )

    async def process_edit_stream(
        self,
        session_id: str,
        item_id: str,
        edit_request: ChatEditRequest,
        *,
        attachments: list[IncomingAttachment] | None = None,
    ) -> AsyncIterable[ProviderStreamEvent | ChatStreamSessionEvent]:
        active_run: ActiveRunHandle | None = None
        run_result: RunResult | None = None
        created_files: list[Path] = []
        try:
            setup, created_files, active_run = await self._prepare_edit_setup(
                session_id,
                item_id,
                edit_request,
                attachments=attachments,
            )
            yield ChatStreamSessionEvent(
                session_id=setup.session.id,
                agent_id=setup.agent.id,
            )
            async for event in self.stream_prepared_chat(setup, signal=active_run.signal):
                yield event
            self.session.commit()
            agent = self.agent_repository.get(setup.agent.id)
            if agent is not None:
                run_result = self.runner.build_run_result_from_agent(agent)
        except ChatServiceValidationError as exc:
            self.session.rollback()
            self.attachment_storage_service.cleanup_files(created_files)
            yield ProviderErrorEvent(error=str(exc))
        except asyncio.CancelledError:
            self.session.rollback()
            self.attachment_storage_service.cleanup_files(created_files)
            if active_run is not None:
                run_result = self._build_cancelled_run_result(active_run.agent_id)
            raise
        except Exception as exc:
            self.session.rollback()
            self.attachment_storage_service.cleanup_files(created_files)
            if active_run is not None:
                run_result = self._build_failed_run_result(
                    active_run.agent_id,
                    str(exc) or "Chat edit failed.",
                )
            yield ProviderErrorEvent(error=str(exc) or "Chat edit failed.")
        finally:
            if active_run is not None:
                await self.active_run_registry.finish(
                    active_run.agent_id,
                    run_result or self._build_failed_run_result(active_run.agent_id, "Chat edit failed."),
                )

    async def process_queue(
        self,
        session_id: str,
        queue_request: ChatQueueRequest,
        *,
        attachments: list[IncomingAttachment] | None = None,
    ) -> ChatQueueResponse:
        created_files: list[Path] = []
        try:
            response, created_files = self._queue_session_input(
                session_id,
                queue_request,
                attachments=attachments,
            )
            self.session.commit()
            return response
        except ChatServiceValidationError:
            self.session.rollback()
            self.attachment_storage_service.cleanup_files(created_files)
            raise
        except Exception:
            self.session.rollback()
            self.attachment_storage_service.cleanup_files(created_files)
            raise

    async def process_delivery(
        self,
        agent_id: str,
        deliver_request: DeliverRequest,
        *,
        include_tool_result: bool = False,
    ) -> ChatResponse:
        try:
            response = await self.deliver_to_agent(
                agent_id,
                deliver_request,
                include_tool_result=include_tool_result,
            )
            self.session.commit()
            return response
        except ChatServiceValidationError:
            self.session.rollback()
            raise
        except Exception:
            self.session.rollback()
            raise

    async def process_cancel(
        self,
        session_id: str,
        *,
        include_tool_result: bool = False,
    ) -> ChatResponse:
        try:
            response = await self.cancel_session_run(
                session_id,
                include_tool_result=include_tool_result,
            )
            self.session.commit()
            return response
        except ChatServiceValidationError:
            self.session.rollback()
            raise
        except Exception:
            self.session.rollback()
            raise

    async def prepare_chat(
        self,
        chat_request: ChatRequest,
        *,
        attachments: list[IncomingAttachment] | None = None,
    ) -> tuple[PreparedChatSetupResult, list[Path]]:
        created_files: list[Path] = []
        try:
            user = self._ensure_default_user()  # TODO: Get real user
            session = self._load_session(chat_request.session_id, user)
            self._validate_session_accepts_new_run(session)
            resolved_config = self._resolve_agent_config(chat_request.agent_config)
            trace_id = uuid4().hex
            agent = self._resolve_session_root_agent(
                session,
                resolved_config,
                trace_id=trace_id,
                has_explicit_config=chat_request.agent_config is not None,
            )
            last_sequence = self.item_repository.get_last_sequence(agent.id)
            existing_session_item_ids = {item.id for item in self.item_repository.list_by_session(session.id)}
            stored_attachments, created_files = self._store_request_attachments(
                user=user,
                session=session,
                attachments=attachments or [],
            )
            self._store_input_items(
                chat_request,
                session,
                agent,
                last_sequence,
                attachments=stored_attachments,
            )
        except ChatServiceValidationError as exc:
            return PreparedChatSetupResult(ok=False, error=str(exc)), created_files

        return PreparedChatSetupResult(
            ok=True,
            value=PreparedChatSetup(
                session=session,
                agent=agent,
                last_sequence=last_sequence,
                existing_session_item_ids=existing_session_item_ids,
            ),
        ), created_files

    def _validate_session_accepts_new_run(self, session: Session) -> None:
        if session.root_agent_id is None:
            return
        root_agent = self.agent_repository.get(session.root_agent_id)
        if root_agent is None:
            return
        if root_agent.status in {AgentStatus.RUNNING, AgentStatus.WAITING}:
            raise ChatServiceValidationError(
                "Session already has an active or waiting run. Use the queue endpoint instead."
            )

    async def _process_edit_internal(
        self,
        session_id: str,
        item_id: str,
        edit_request: ChatEditRequest,
        *,
        attachments: list[IncomingAttachment] | None = None,
        include_tool_result: bool,
    ) -> tuple[ChatResponse, list[Path], ActiveRunHandle]:
        setup, created_files, active_run = await self._prepare_edit_setup(
            session_id,
            item_id,
            edit_request,
            attachments=attachments,
        )
        response = await self.execute_chat(
            setup.agent.id,
            setup.last_sequence,
            existing_session_item_ids=setup.existing_session_item_ids,
            include_tool_result=include_tool_result,
            signal=active_run.signal,
        )
        return response, created_files, active_run

    async def _prepare_edit_setup(
        self,
        session_id: str,
        item_id: str,
        edit_request: ChatEditRequest,
        *,
        attachments: list[IncomingAttachment] | None = None,
    ) -> tuple[PreparedChatSetup, list[Path], ActiveRunHandle]:
        user = self._ensure_default_user()
        session = self._ensure_session_owner(session_id, action="edit")
        root_agent_id = session.root_agent_id
        if not root_agent_id:
            raise ChatServiceNotFoundError(f"Root agent not found for session: {session_id}")

        existing_item = self.item_repository.get(item_id)
        if existing_item is None or existing_item.session_id != session.id:
            raise ChatServiceNotFoundError(f"Item not found in session: {item_id}")
        if existing_item.type != ItemType.MESSAGE or existing_item.role != MessageRole.USER:
            raise ChatServiceValidationError("Only user message items can be edited.")
        if existing_item.agent_id != root_agent_id:
            raise ChatServiceValidationError("Only root transcript user messages can be edited.")

        if self.active_run_registry.is_active(root_agent_id):
            raise ChatServiceValidationError("Cannot edit while the root run is active.")

        stored_attachments, created_files = self._store_request_attachments(
            user=user,
            session=session,
            attachments=attachments or [],
        )
        updated_attachments = self._merge_retained_attachments(
            existing_item=existing_item,
            retain_attachment_ids=edit_request.retain_attachment_ids,
            new_attachments=stored_attachments,
            new_item_id=existing_item.id,
        )
        updated_item = Item(
            id=existing_item.id,
            session_id=existing_item.session_id,
            agent_id=existing_item.agent_id,
            sequence=existing_item.sequence,
            type=existing_item.type,
            role=existing_item.role,
            content=edit_request.message,
            call_id=existing_item.call_id,
            name=existing_item.name,
            arguments_json=existing_item.arguments_json,
            output=existing_item.output,
            is_error=existing_item.is_error,
            created_at=existing_item.created_at,
            attachments=updated_attachments,
            edited_at=utcnow(),
        )
        self.item_repository.save(updated_item)

        rewound_setup = self._rewind_session_from_item(session, root_agent_id=root_agent_id, item_id=item_id)
        active_run = await self.active_run_registry.start(root_agent_id)
        return rewound_setup, created_files, active_run

    def _queue_session_input(
        self,
        session_id: str,
        queue_request: ChatQueueRequest,
        *,
        attachments: list[IncomingAttachment] | None = None,
    ) -> tuple[ChatQueueResponse, list[Path]]:
        user = self._ensure_default_user()
        session = self._ensure_session_owner(session_id, action="queue")
        root_agent_id = session.root_agent_id
        if not root_agent_id:
            raise ChatServiceNotFoundError(f"Root agent not found for session: {session_id}")

        root_agent = self.agent_repository.get(root_agent_id)
        if root_agent is None:
            raise ChatServiceNotFoundError(f"Agent not found: {root_agent_id}")
        if root_agent.status not in {AgentStatus.RUNNING, AgentStatus.WAITING}:
            raise ChatServiceValidationError("Queue accepts input only for running or waiting sessions.")

        stored_attachments, created_files = self._store_request_attachments(
            user=user,
            session=session,
            attachments=attachments or [],
        )
        queued_input = self.queued_input_repository.save(
            QueuedInput(
                id=uuid4().hex,
                session_id=session.id,
                agent_id=root_agent.id,
                message=queue_request.message,
                attachments=[
                    QueuedInputAttachment(
                        file_name=attachment.file_name,
                        media_type=attachment.media_type,
                        size_bytes=attachment.size_bytes,
                        path=attachment.path,
                    )
                    for attachment in stored_attachments
                ],
                accepted_at=utcnow(),
            )
        )
        queue_position = self.message_queue.pending_count(session.id, root_agent.id)
        return ChatQueueResponse(
            session_id=session.id,
            queued_input_id=queued_input.id,
            accepted_at=queued_input.accepted_at or utcnow(),
            queue_position=queue_position,
        ), created_files

    async def stream_prepared_chat(
        self,
        setup: PreparedChatSetup,
        *,
        signal: CancellationSignal,
    ) -> AsyncIterable[ProviderStreamEvent]:
        async for event in self.runner.run_agent_stream(
            setup.agent.id,
            last_agent_sequence=setup.last_sequence,
            signal=signal,
        ):
            yield event

    async def execute_chat(
        self,
        agent_id: str,
        last_sequence: int,
        *,
        existing_session_item_ids: set[str] | None = None,
        include_tool_result: bool = False,
        signal: CancellationSignal | None = None,
    ) -> ChatResponse:
        result = await self.runner.run_agent(
            agent_id,
            last_agent_sequence=last_sequence,
            signal=signal,
        )
        agent = result.agent or self.agent_repository.get(agent_id)
        if agent is None:
            raise RuntimeError(f"Agent disappeared during execution: {agent_id}")

        return ChatResponse(
            id=agent.id,
            agent_id=agent.id,
            session_id=agent.session_id,
            status=result.status,
            model=agent.config.model,
            output=self._build_chat_output(
                agent,
                last_sequence=last_sequence,
                include_tool_result=include_tool_result,
                existing_session_item_ids=existing_session_item_ids or set(),
            ),
            waiting_for=self._build_waiting_for_output(agent.waiting_for),
            error=result.error,
        )

    async def cancel_session_run(
        self,
        session_id: str,
        *,
        include_tool_result: bool = False,
    ) -> ChatResponse:
        session = self._ensure_session_owner(session_id, action="cancel")
        agent_id = session.root_agent_id
        if not agent_id:
            raise ChatServiceNotFoundError(f"Root agent not found for session: {session_id}")

        result = await self.active_run_registry.cancel(agent_id)
        agent = self.agent_repository.get(agent_id)
        if agent is None:
            raise ChatServiceNotFoundError(f"Agent not found: {agent_id}")

        resolved_result = result or self.runner.build_run_result_from_agent(agent)
        return ChatResponse(
            id=agent.id,
            agent_id=agent.id,
            session_id=agent.session_id,
            status=resolved_result.status,
            model=agent.config.model,
            output=self._build_chat_output(
                agent,
                last_sequence=0,
                include_tool_result=include_tool_result,
                existing_session_item_ids=set(),
            ),
            waiting_for=self._build_waiting_for_output(agent.waiting_for),
            error=resolved_result.error,
        )

    async def deliver_to_agent(
        self,
        agent_id: str,
        deliver_request: DeliverRequest,
        *,
        include_tool_result: bool = False,
    ) -> ChatResponse:
        self._ensure_agent_owner(agent_id)
        current_agent = self.agent_repository.get(agent_id)
        if current_agent is None:
            raise ChatServiceNotFoundError(f"Agent not found: {agent_id}")
        last_sequence = self.item_repository.get_last_sequence(agent_id)
        existing_session_item_ids = {item.id for item in self.item_repository.list_by_session(current_agent.session_id)}
        trace_id = uuid4().hex
        result_payload = self._build_delivery_result(deliver_request)
        result = await self.runner.deliver_result(
            agent_id,
            call_id=deliver_request.call_id,
            result=result_payload,
            trace_id=trace_id,
        )
        if result.error is not None and result.error.startswith("Waiting call not found:"):
            raise ChatServiceNotFoundError(result.error)
        agent = result.agent or self.agent_repository.get(agent_id)
        if agent is None:
            raise RuntimeError(f"Agent disappeared during delivery: {agent_id}")
        return ChatResponse(
            id=agent.id,
            agent_id=agent.id,
            session_id=agent.session_id,
            status=result.status,
            model=agent.config.model,
            output=self._build_chat_output(
                agent,
                last_sequence=last_sequence,
                include_tool_result=include_tool_result,
                existing_session_item_ids=existing_session_item_ids,
            ),
            waiting_for=self._build_waiting_for_output(agent.waiting_for),
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

    def _ensure_agent_owner(self, agent_id: str) -> None:
        current_user = self._ensure_default_user()
        agent = self.agent_repository.get(agent_id)
        if agent is None:
            raise ChatServiceNotFoundError(f"Agent not found: {agent_id}")

        session = self.session_repository.get(agent.session_id)
        if session is None:
            raise RuntimeError(f"Session not found for agent: {agent_id}")

        if session.user_id != current_user.id:
            raise PermissionError(f"User {current_user.id} cannot deliver results to agent {agent_id}")

    def _ensure_session_owner(self, session_id: str, *, action: str = "access") -> Session:
        current_user = self._ensure_default_user()
        session = self.session_repository.get(session_id)
        if session is None:
            raise ChatServiceNotFoundError(f"Session not found: {session_id}")

        if session.user_id != current_user.id:
            raise PermissionError(f"User {current_user.id} cannot {action} session {session_id}")

        return session

    def _build_failed_run_result(self, agent_id: str, error: str) -> RunResult:
        agent = self.agent_repository.get(agent_id)
        return RunResult(
            ok=False,
            status="failed",
            agent=agent,
            error=error,
        )

    def _build_cancelled_run_result(self, agent_id: str) -> RunResult:
        agent = self.agent_repository.get(agent_id)
        return RunResult(
            ok=False,
            status="cancelled",
            agent=agent,
        )

    def _load_session(self, session_id: str | None, user: User) -> Session:
        if not session_id:
            now = utcnow()
            session = Session(
                id=uuid4().hex,
                user_id=user.id,
                root_agent_id=None,
                status=SessionStatus.ACTIVE,
                title=None,
                created_at=now,
                updated_at=now,
            )
            saved_session = self.session_repository.save(session)
            layout = self.workspace_layout_service.ensure_session_workspace(user=user, session=saved_session)
            saved_session.workspace_path = str(layout.root)
            self.session_repository.save(saved_session)
            # Commit immediately so that other DB connections (e.g. markdown event
            # logger's resolver) can see the new session and its workspace_path
            # while events are still being emitted during this request.
            self.session.commit()
            return saved_session

        session = self.session_repository.get(session_id)
        if session is None:
            raise ChatServiceValidationError(f"Session not found: {session_id}")
        if session.user_id != user.id:
            raise ChatServiceValidationError(f"Session not found: {session_id}")
        return session

    def _resolve_agent_config(self, request_config: ChatAgentConfigInput | None) -> ResolvedAgentConfig:
        default_model = f"openrouter:{self.settings.OPEN_ROUTER_LLM_MODEL}"
        agent_name = self.settings.DEFAULT_AGENT
        if request_config is not None and request_config.agent_name:
            agent_name = request_config.agent_name

        try:
            loaded_agent = self.agent_loader.load_agent_by_name(agent_name)
        except ValueError as exc:
            raise ChatServiceValidationError(str(exc)) from exc
        except FileNotFoundError as exc:
            raise ChatServiceNotFoundError(f"Agent template not found: {agent_name}") from exc

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
            temperature=request_config.temperature
            if request_config.temperature is not None
            else base_config.temperature,
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

    def _resolve_session_root_agent(
        self,
        session: Session,
        config: ResolvedAgentConfig,
        *,
        trace_id: str,
        has_explicit_config: bool,
    ) -> Agent:
        now = utcnow()

        if session.root_agent_id is not None:
            agent = self.agent_repository.get(session.root_agent_id)
            if agent is None:
                raise RuntimeError(f"Session integrity error: root agent not found: {session.root_agent_id}")

            # Only rewrite identity/config when the caller explicitly supplied a new agent_config.
            # Otherwise the next turn would overwrite the session's root agent with DEFAULT_AGENT.
            if has_explicit_config:
                agent.agent_name = config.agent_name
                agent.config = AgentConfig(
                    model=config.model,
                    task=config.task,
                    tools=config.tools,
                    temperature=config.temperature,
                )
            agent.trace_id = trace_id
            agent.status = AgentStatus.PENDING
            agent.waiting_for = []
            agent.updated_at = now
            return self.agent_repository.save(agent)

        agent_config = AgentConfig(
            model=config.model,
            task=config.task,
            tools=config.tools,
            temperature=config.temperature,
        )

        agent_id = uuid4().hex
        agent = Agent(
            id=agent_id,
            session_id=session.id,
            trace_id=trace_id,
            root_agent_id=agent_id,
            parent_id=None,
            source_call_id=None,
            depth=0,
            agent_name=config.agent_name,
            status=AgentStatus.PENDING,
            turn_count=0,
            waiting_for=[],
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
        *,
        attachments: list[StoredAttachment],
    ) -> None:
        user_message_count = sum(
            1
            for input_item in chat_request.input
            if input_item.type == "message" and input_item.role == MessageRole.USER.value
        )
        if attachments and user_message_count != 1:
            raise ChatServiceValidationError("Attachments require exactly one user message in the request.")

        sequence = last_sequence
        for input_item in chat_request.input:
            if input_item.type != "message":
                continue

            sequence += 1
            item_id = uuid4().hex
            item = Item(
                id=item_id,
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
                attachments=self._build_item_attachments(item_id=item_id, stored_attachments=attachments)
                if attachments and input_item.role == MessageRole.USER.value
                else [],
            )
            self.item_repository.save(item)

    def _store_request_attachments(
        self,
        *,
        user: User,
        session: Session,
        attachments: list[IncomingAttachment],
    ) -> tuple[list[StoredAttachment], list[Path]]:
        return self.attachment_storage_service.store(
            user=user,
            session=session,
            attachments=attachments,
        )

    def _merge_retained_attachments(
        self,
        *,
        existing_item: Item,
        retain_attachment_ids: list[str],
        new_attachments: list[StoredAttachment],
        new_item_id: str,
    ) -> list[Attachment]:
        retain_set = set(retain_attachment_ids)
        retained = [attachment for attachment in existing_item.attachments if attachment.id in retain_set]
        missing = retain_set.difference({attachment.id for attachment in existing_item.attachments})
        if missing:
            raise ChatServiceValidationError("retain_attachment_ids contains unknown attachment ids.")

        return [
            *retained,
            *self._build_item_attachments(item_id=new_item_id, stored_attachments=new_attachments),
        ]

    def _build_item_attachments(
        self,
        *,
        item_id: str,
        stored_attachments: list[StoredAttachment],
    ) -> list[Attachment]:
        return [
            Attachment(
                id=uuid4().hex,
                item_id=item_id,
                file_name=attachment.file_name,
                media_type=attachment.media_type,
                size_bytes=attachment.size_bytes,
                path=attachment.path,
                created_at=utcnow(),
            )
            for attachment in stored_attachments
        ]

    def _rewind_session_from_item(
        self,
        session: Session,
        *,
        root_agent_id: str,
        item_id: str,
    ) -> PreparedChatSetup:
        chronological_items = self.item_repository.list_by_session_chronological(session.id)
        rewind_index = next((index for index, item in enumerate(chronological_items) if item.id == item_id), None)
        if rewind_index is None:
            raise ChatServiceNotFoundError(f"Item not found in session: {item_id}")

        kept_items = chronological_items[: rewind_index + 1]
        removed_items = chronological_items[rewind_index + 1 :]
        self.item_repository.delete_many([item.id for item in removed_items])
        self.message_queue.clear_pending(session.id, root_agent_id)

        kept_agent_ids = {root_agent_id, *(item.agent_id for item in kept_items)}
        removable_agent_ids: list[str] = []
        for agent in self.agent_repository.list_by_session(session.id):
            if agent.id == root_agent_id:
                agent.status = AgentStatus.PENDING
                agent.waiting_for = []
                agent.updated_at = utcnow()
                self.agent_repository.save(agent)
                continue
            if agent.id not in kept_agent_ids:
                removable_agent_ids.append(agent.id)
                continue
            if agent.status == AgentStatus.WAITING:
                agent.waiting_for = []
                agent.status = AgentStatus.COMPLETED
                agent.updated_at = utcnow()
                self.agent_repository.save(agent)

        self.agent_repository.delete_many(removable_agent_ids)

        root_agent = self.agent_repository.get(root_agent_id)
        if root_agent is None:
            raise ChatServiceNotFoundError(f"Agent not found: {root_agent_id}")
        anchor_item = self.item_repository.get(item_id)
        if anchor_item is None:
            raise ChatServiceNotFoundError(f"Item not found in session: {item_id}")

        return PreparedChatSetup(
            session=session,
            agent=root_agent,
            last_sequence=anchor_item.sequence,
            existing_session_item_ids={item.id for item in kept_items},
        )

    @staticmethod
    def _build_response_output(
        items: list[Item],
        *,
        include_tool_result: bool = False,
    ) -> list[TextOutputItem | FunctionCallOutputItem | FunctionCallResultOutputItem]:
        output: list[TextOutputItem | FunctionCallOutputItem | FunctionCallResultOutputItem] = []

        for item in items:
            if item.type == ItemType.MESSAGE and item.role == MessageRole.ASSISTANT and item.content:
                output.append(
                    TextOutputItem(
                        text=item.content,
                        agent_id=item.agent_id,
                        created_at=item.created_at,
                    )
                )
                continue

            if item.type == ItemType.FUNCTION_CALL:
                output.append(
                    FunctionCallOutputItem(
                        call_id=item.call_id or "",
                        name=item.name or "",
                        arguments=ChatService._deserialize_arguments(item.arguments_json),
                        agent_id=item.agent_id,
                        created_at=item.created_at,
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
                        agent_id=item.agent_id,
                        created_at=item.created_at,
                    )
                )

        return output

    @staticmethod
    def _build_waiting_for_output(waiting_for: list[WaitingForEntry]) -> list[WaitingForOutputItem]:
        return [
            WaitingForOutputItem(
                call_id=entry.call_id,
                type=entry.type,
                name=entry.name,
                description=entry.description,
                agent_id=entry.agent_id,
            )
            for entry in waiting_for
        ]

    def _build_chat_output(
        self,
        agent: Agent,
        *,
        last_sequence: int,
        include_tool_result: bool,
        existing_session_item_ids: set[str],
    ) -> list[TextOutputItem | FunctionCallOutputItem | FunctionCallResultOutputItem]:
        if include_tool_result:
            session_items = self.item_repository.list_by_session_chronological(agent.session_id)
            new_items = [item for item in session_items if item.id not in existing_session_item_ids]
            output = self._build_response_output(new_items, include_tool_result=True)
            return self._append_waiting_tool_results(agent, output, include_tool_result=True)

        response_items = self.item_repository.list_by_agent_after_sequence(agent.id, last_sequence)
        return self._build_response_output(response_items, include_tool_result=False)

    def _append_waiting_tool_results(
        self,
        agent: Agent,
        output: list[TextOutputItem | FunctionCallOutputItem | FunctionCallResultOutputItem],
        *,
        include_tool_result: bool,
    ) -> list[TextOutputItem | FunctionCallOutputItem | FunctionCallResultOutputItem]:
        if not include_tool_result or agent.status != AgentStatus.WAITING:
            return output

        waiting_agents = self._collect_active_waiting_agents(agent)
        waiting_outputs = [
            FunctionCallResultOutputItem(
                call_id=entry.call_id,
                name=entry.name,
                output=entry.description,
                is_error=False,
                agent_id=waiting_agent.id,
                created_at=None,
            )
            for waiting_agent in waiting_agents
            for entry in waiting_agent.waiting_for
            if entry.description
        ]
        return [*output, *waiting_outputs]

    def _collect_active_waiting_agents(self, root_agent: Agent) -> list[Agent]:
        waiting_agents: list[Agent] = []
        seen_agent_ids: set[str] = set()
        stack: list[Agent] = [root_agent]

        while stack:
            current = stack.pop()
            if current.id in seen_agent_ids or current.status != AgentStatus.WAITING:
                continue

            seen_agent_ids.add(current.id)
            waiting_agents.append(current)

            for entry in current.waiting_for:
                if entry.type != "agent" or not entry.agent_id:
                    continue
                child_agent = self.agent_repository.get(entry.agent_id)
                if child_agent is not None:
                    stack.append(child_agent)

        waiting_agents.sort(key=lambda waiting_agent: (-waiting_agent.depth, waiting_agent.created_at))
        return waiting_agents

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

    @staticmethod
    def _build_delivery_result(deliver_request: DeliverRequest) -> dict[str, Any]:
        if deliver_request.is_error:
            return {"ok": False, "error": ChatService._serialize_delivery_output(deliver_request.output)}
        return {"ok": True, "output": ChatService._serialize_delivery_output(deliver_request.output)}

    @staticmethod
    def _serialize_delivery_output(value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return json.loads(json.dumps(value, ensure_ascii=True, default=str))
