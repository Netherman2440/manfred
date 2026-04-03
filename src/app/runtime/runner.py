from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from app.db.base import utcnow
from app.domain import Agent, AgentStatus, Item, ItemType, MessageRole, Session
from app.domain.repositories import AgentRepository, ItemRepository, SessionRepository
from app.events import (
    AgentCompletedEvent,
    AgentFailedEvent,
    AgentStartedEvent,
    EventBus,
    GenerationCompletedEvent,
    ToolCalledEvent,
    ToolCompletedEvent,
    ToolFailedEvent,
    TurnCompletedEvent,
    TurnStartedEvent,
    build_event_context,
)
from app.providers import (
    ProviderFunctionCallInputItem,
    ProviderFunctionCallOutputInputItem,
    ProviderFunctionCallOutputItem,
    ProviderMessageInputItem,
    ProviderRegistry,
    ProviderRequest,
    ProviderResponse,
    ProviderTextOutputItem,
    ProviderUsage,
)
from app.tools.registry import ToolRegistry


@dataclass(slots=True)
class AgentRunContext:
    agent: Agent
    session: Session
    items: list[Item]
    trace_id: str
    last_agent_sequence: int


@dataclass(slots=True)
class TurnResult:
    status: Literal["continue", "completed", "failed"]
    agent: Agent
    error: str | None = None
    usage: ProviderUsage | None = None


@dataclass(slots=True)
class RunResult:
    ok: bool
    status: Literal["completed", "failed"]
    agent: Agent | None = None
    error: str | None = None


class Runner:
    def __init__(
        self,
        *,
        agent_repository: AgentRepository,
        session_repository: SessionRepository,
        item_repository: ItemRepository,
        tool_registry: ToolRegistry,
        provider_registry: ProviderRegistry,
        event_bus: EventBus,
    ) -> None:
        self.agent_repository = agent_repository
        self.session_repository = session_repository
        self.item_repository = item_repository
        self.tool_registry = tool_registry
        self.provider_registry = provider_registry
        self.event_bus = event_bus

    async def run_agent(
        self,
        agent_id: str,
        *,
        max_turns: int = 10,
        last_agent_sequence: int = 0,
    ) -> RunResult:
        context = self.load_agent_context(
            agent_id,
            trace_id=uuid4().hex,
            last_agent_sequence=last_agent_sequence,
        )
        if context.agent.status == AgentStatus.WAITING:
            return RunResult(
                ok=False,
                status="failed",
                agent=context.agent,
                error="Waiting agents are not implemented yet.",
            )

        context.agent.status = AgentStatus.RUNNING
        context.agent.updated_at = utcnow()
        context.agent = self.agent_repository.save(context.agent)
        run_started_at = utcnow()
        total_usage = ProviderUsage()

        self.event_bus.emit(
            AgentStartedEvent(
                ctx=build_event_context(context.agent, context.trace_id),
                model=context.agent.config.model,
                task=context.agent.config.task,
                agent_name=context.agent.agent_name,
                user_id=context.session.user_id,
                user_input=self._find_run_user_input(context),
            )
        )

        turns_executed = 0

        while context.agent.status == AgentStatus.RUNNING:
            if turns_executed >= max_turns:
                return self._fail_run(
                    context,
                    error="Agent exceeded max_turns.",
                )

            self.event_bus.emit(
                TurnStartedEvent(
                    ctx=build_event_context(context.agent, context.trace_id),
                    turn_count=context.agent.turn_count,
                )
            )

            turn = await self.execute_turn(context)
            context.agent = turn.agent
            total_usage = self._add_usage(total_usage, turn.usage)

            if turn.status != "failed":
                self.event_bus.emit(
                    TurnCompletedEvent(
                        ctx=build_event_context(context.agent, context.trace_id),
                        turn_count=context.agent.turn_count,
                        usage=turn.usage,
                    )
                )

            context.agent.turn_count += 1
            context.agent.updated_at = utcnow()
            context.agent = self.agent_repository.save(context.agent)
            turns_executed += 1

            if turn.status == "continue":
                context = self.reload_context(context)
                continue

            if turn.status == "completed":
                self.event_bus.emit(
                    AgentCompletedEvent(
                        ctx=build_event_context(context.agent, context.trace_id),
                        duration_ms=self._duration_ms(run_started_at),
                        usage=total_usage,
                        result=self._find_run_result(context),
                    )
                )
                return RunResult(ok=True, status="completed", agent=context.agent)

            return self._fail_run(
                context,
                error=turn.error or "Agent execution failed.",
            )

        return self._fail_run(context, error="Agent stopped unexpectedly.")

    async def execute_turn(self, context: AgentRunContext) -> TurnResult:
        resolved = self.provider_registry.resolve(context.agent.config.model)
        if resolved is None:
            return TurnResult(
                status="failed",
                agent=context.agent,
                error=f"Unknown provider or model reference: {context.agent.config.model}",
            )

        request_input = self.map_items_to_provider_input(context.items)
        request = ProviderRequest(
            model=resolved.model,
            instructions=context.agent.config.task,
            input=request_input,
            tools=context.agent.config.tools or [],
            temperature=context.agent.config.temperature,
        )
        generation_started_at = utcnow()
        generation_timer_started_at = perf_counter()

        try:
            response = await resolved.provider.generate(request)
        except Exception as exc:
            return TurnResult(status="failed", agent=context.agent, error=str(exc) or "Provider call failed.")

        self.event_bus.emit(
            GenerationCompletedEvent(
                ctx=build_event_context(context.agent, context.trace_id),
                model=resolved.model,
                instructions=request.instructions,
                input=request_input,
                output=response.output,
                usage=response.usage,
                duration_ms=self._duration_ms(generation_started_at, generation_timer_started_at),
                start_time=generation_started_at,
            )
        )

        return await self.handle_turn_response(context, response)

    async def handle_turn_response(
        self,
        context: AgentRunContext,
        response: ProviderResponse,
    ) -> TurnResult:
        context.items.extend(self.store_provider_output(context.agent, context.session, response))

        function_calls = [
            output_item
            for output_item in response.output
            if isinstance(output_item, ProviderFunctionCallOutputItem)
        ]

        if not function_calls:  # TODO: support reasoning items when provider exposes them
            context.agent.status = AgentStatus.COMPLETED
            return TurnResult(status="completed", agent=context.agent, usage=response.usage)

        for function_call in function_calls:
            self.event_bus.emit(
                ToolCalledEvent(
                    ctx=build_event_context(context.agent, context.trace_id),
                    call_id=function_call.call_id,
                    name=function_call.name,
                    arguments=function_call.arguments,
                )
            )

            tool_started_at = utcnow()
            tool_timer_started_at = perf_counter()
            tool = self.tool_registry.get(function_call.name)
            if tool is None:
                error_message = f"Tool not found: {function_call.name}"
                tool_output = self.store_tool_output(
                    context.agent,
                    context.session,
                    call_id=function_call.call_id,
                    name=function_call.name,
                    result={"ok": False, "error": error_message},
                    is_error=True,
                )
                context.items.append(tool_output)
                self.event_bus.emit(
                    ToolFailedEvent(
                        ctx=build_event_context(context.agent, context.trace_id),
                        call_id=function_call.call_id,
                        name=function_call.name,
                        arguments=function_call.arguments,
                        error=error_message,
                        duration_ms=self._duration_ms(tool_started_at, tool_timer_started_at),
                        start_time=tool_started_at,
                    )
                )
                continue

            if tool.type != "sync":
                error_message = f"Tool type '{tool.type}' is not implemented yet."
                self.event_bus.emit(
                    ToolFailedEvent(
                        ctx=build_event_context(context.agent, context.trace_id),
                        call_id=function_call.call_id,
                        name=function_call.name,
                        arguments=function_call.arguments,
                        error=error_message,
                        duration_ms=self._duration_ms(tool_started_at, tool_timer_started_at),
                        start_time=tool_started_at,
                    )
                )
                return TurnResult(
                    status="failed",
                    agent=context.agent,
                    error=error_message,
                    usage=response.usage,
                )

            result = await self.tool_registry.execute(function_call.name, function_call.arguments)
            tool_output = self.store_tool_output(
                context.agent,
                context.session,
                call_id=function_call.call_id,
                name=function_call.name,
                result=result,
                is_error=not bool(result.get("ok")),
            )
            context.items.append(tool_output)

            duration_ms = self._duration_ms(tool_started_at, tool_timer_started_at)
            if bool(result.get("ok")):
                self.event_bus.emit(
                    ToolCompletedEvent(
                        ctx=build_event_context(context.agent, context.trace_id),
                        call_id=function_call.call_id,
                        name=function_call.name,
                        arguments=function_call.arguments,
                        output=dict(result),
                        duration_ms=duration_ms,
                        start_time=tool_started_at,
                    )
                )
                continue

            self.event_bus.emit(
                ToolFailedEvent(
                    ctx=build_event_context(context.agent, context.trace_id),
                    call_id=function_call.call_id,
                    name=function_call.name,
                    arguments=function_call.arguments,
                    error=str(result.get("error") or "Tool execution failed."),
                    duration_ms=duration_ms,
                    start_time=tool_started_at,
                )
            )

        return TurnResult(status="continue", agent=context.agent, usage=response.usage)

    def load_agent_context(
        self,
        agent_id: str,
        *,
        trace_id: str,
        last_agent_sequence: int,
    ) -> AgentRunContext:
        agent = self.agent_repository.get(agent_id)
        if agent is None:
            raise RuntimeError(f"Agent not found: {agent_id}")

        session = self.session_repository.get(agent.session_id)
        if session is None:
            raise RuntimeError(f"Session not found for agent: {agent_id}")

        items = self.item_repository.list_by_agent(agent.id)
        return AgentRunContext(
            agent=agent,
            session=session,
            items=items,
            trace_id=trace_id,
            last_agent_sequence=last_agent_sequence,
        )

    def reload_context(self, context: AgentRunContext) -> AgentRunContext:
        return self.load_agent_context(
            context.agent.id,
            trace_id=context.trace_id,
            last_agent_sequence=context.last_agent_sequence,
        )

    @staticmethod
    def map_items_to_provider_input(items: list[Item]) -> list[
        ProviderMessageInputItem | ProviderFunctionCallInputItem | ProviderFunctionCallOutputInputItem
    ]:
        provider_input: list[
            ProviderMessageInputItem | ProviderFunctionCallInputItem | ProviderFunctionCallOutputInputItem
        ] = []

        for item in items:
            if item.type == ItemType.MESSAGE and item.content is not None and item.role is not None:
                provider_input.append(
                    ProviderMessageInputItem(
                        role=item.role.value,
                        content=item.content,
                    )
                )
                continue

            if item.type == ItemType.FUNCTION_CALL:
                arguments = Runner._deserialize_arguments(item.arguments_json)
                provider_input.append(
                    ProviderFunctionCallInputItem(
                        call_id=item.call_id or "",
                        name=item.name or "",
                        arguments=arguments,
                    )
                )
                continue

            if item.type == ItemType.FUNCTION_CALL_OUTPUT:
                provider_input.append(
                    ProviderFunctionCallOutputInputItem(
                        call_id=item.call_id or "",
                        name=item.name or "",
                        output=item.output or "",
                    )
                )

        return provider_input

    def store_provider_output(
        self,
        agent: Agent,
        session: Session,
        response: ProviderResponse,
    ) -> list[Item]:
        stored_items: list[Item] = []
        next_sequence = self.item_repository.get_last_sequence(agent.id)
        text_parts = [
            output_item.text
            for output_item in response.output
            if isinstance(output_item, ProviderTextOutputItem) and output_item.text
        ]

        if text_parts:
            next_sequence += 1
            item = Item(
                id=uuid4().hex,
                session_id=session.id,
                agent_id=agent.id,
                sequence=next_sequence,
                type=ItemType.MESSAGE,
                role=MessageRole.ASSISTANT,
                content="".join(text_parts),
                call_id=None,
                name=None,
                arguments_json=None,
                output=None,
                is_error=False,
                created_at=utcnow(),
            )
            stored_items.append(self.item_repository.save(item))

        for output_item in response.output:
            if not isinstance(output_item, ProviderFunctionCallOutputItem):
                continue

            next_sequence += 1
            item = Item(
                id=uuid4().hex,
                session_id=session.id,
                agent_id=agent.id,
                sequence=next_sequence,
                type=ItemType.FUNCTION_CALL,
                role=MessageRole.ASSISTANT,
                content=None,
                call_id=output_item.call_id,
                name=output_item.name,
                arguments_json=json.dumps(output_item.arguments, ensure_ascii=True),
                output=None,
                is_error=False,
                created_at=utcnow(),
            )
            stored_items.append(self.item_repository.save(item))

        return stored_items

    def store_tool_output(
        self,
        agent: Agent,
        session: Session,
        *,
        call_id: str,
        name: str,
        result: dict[str, Any],
        is_error: bool,
    ) -> Item:
        sequence = self.item_repository.get_last_sequence(agent.id) + 1
        item = Item(
            id=uuid4().hex,
            session_id=session.id,
            agent_id=agent.id,
            sequence=sequence,
            type=ItemType.FUNCTION_CALL_OUTPUT,
            role=MessageRole.SYSTEM,
            content=None,
            call_id=call_id,
            name=name,
            arguments_json=None,
            output=json.dumps(result, ensure_ascii=True),
            is_error=is_error,
            created_at=utcnow(),
        )
        return self.item_repository.save(item)

    @staticmethod
    def _deserialize_arguments(raw_arguments: str | None) -> dict[str, Any]:
        if not raw_arguments:
            return {}
        try:
            payload = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _fail_run(self, context: AgentRunContext, *, error: str) -> RunResult:
        context.agent.status = AgentStatus.FAILED
        context.agent.updated_at = utcnow()
        context.agent = self.agent_repository.save(context.agent)
        self.event_bus.emit(
            AgentFailedEvent(
                ctx=build_event_context(context.agent, context.trace_id),
                error=error,
            )
        )
        return RunResult(
            ok=False,
            status="failed",
            agent=context.agent,
            error=error,
        )

    @staticmethod
    def _add_usage(total: ProviderUsage, usage: ProviderUsage | None) -> ProviderUsage:
        if usage is None:
            return total
        return ProviderUsage(
            input_tokens=total.input_tokens + usage.input_tokens,
            output_tokens=total.output_tokens + usage.output_tokens,
            total_tokens=total.total_tokens + usage.total_tokens,
            cached_tokens=total.cached_tokens + usage.cached_tokens,
        )

    @staticmethod
    def _duration_ms(started_at: object, monotonic_started_at: float | None = None) -> int:
        if monotonic_started_at is not None:
            return max(0, int((perf_counter() - monotonic_started_at) * 1000))
        return max(0, int((utcnow() - started_at).total_seconds() * 1000))

    @staticmethod
    def _find_run_user_input(context: AgentRunContext) -> str | None:
        user_input: str | None = None
        for item in context.items:
            if item.sequence <= context.last_agent_sequence:
                continue
            if item.type == ItemType.MESSAGE and item.role == MessageRole.USER and item.content:
                user_input = item.content
        return user_input

    @staticmethod
    def _find_run_result(context: AgentRunContext) -> str | None:
        result: str | None = None
        for item in context.items:
            if item.sequence <= context.last_agent_sequence:
                continue
            if item.type == ItemType.MESSAGE and item.role == MessageRole.ASSISTANT and item.content:
                result = item.content
        return result
