from __future__ import annotations

import json
from collections.abc import AsyncIterable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from app.db.base import utcnow
from app.domain import Agent, AgentConfig, AgentStatus, Item, ItemType, MessageRole, Session, WaitingForEntry
from app.domain.repositories import AgentRepository, ItemRepository, SessionRepository
from app.events import (
    AgentCompletedEvent,
    AgentFailedEvent,
    AgentResumedEvent,
    AgentStartedEvent,
    AgentWaitingEvent,
    EventBus,
    GenerationCompletedEvent,
    ToolCalledEvent,
    ToolCompletedEvent,
    ToolFailedEvent,
    TurnCompletedEvent,
    TurnStartedEvent,
    build_event_context,
)
from app.mcp import McpManager
from app.providers import (
    ProviderDoneEvent,
    ProviderErrorEvent,
    ProviderFunctionCallInputItem,
    ProviderFunctionCallOutputInputItem,
    ProviderFunctionCallOutputItem,
    ProviderMessageInputItem,
    ProviderRegistry,
    ProviderRequest,
    ProviderResponse,
    ProviderStreamEvent,
    ProviderTextOutputItem,
    ProviderUsage,
)
from app.services.agent_loader import AgentLoader
from app.tools.registry import ToolRegistry
from app.utils.string_validator import _require_non_empty_string


@dataclass(slots=True)
class AgentRunContext:
    agent: Agent
    session: Session
    items: list[Item]
    trace_id: str
    last_agent_sequence: int


@dataclass(slots=True)
class TurnResult:
    status: Literal["continue", "completed", "waiting", "failed"]
    agent: Agent
    error: str | None = None
    usage: ProviderUsage | None = None
    error_emitted: bool = False


@dataclass(slots=True)
class RunResult:
    ok: bool
    status: Literal["completed", "waiting", "failed"]
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
        mcp_manager: McpManager,
        provider_registry: ProviderRegistry,
        event_bus: EventBus,
        agent_loader: AgentLoader,
        max_delegation_depth: int,
    ) -> None:
        self.agent_repository = agent_repository
        self.session_repository = session_repository
        self.item_repository = item_repository
        self.tool_registry = tool_registry
        self.mcp_manager = mcp_manager
        self.provider_registry = provider_registry
        self.event_bus = event_bus
        self.agent_loader = agent_loader
        self.max_delegation_depth = max_delegation_depth

    async def run_agent(
        self,
        agent_id: str,
        *,
        max_turns: int = 10,
        last_agent_sequence: int = 0,
        trace_id: str | None = None,
    ) -> RunResult:
        context = self.load_agent_context(
            agent_id,
            trace_id=trace_id,
            last_agent_sequence=last_agent_sequence,
        )
        if context.agent.status == AgentStatus.WAITING:
            return RunResult(
                ok=True,
                status="waiting",
                agent=context.agent,
            )

        context.agent.trace_id = context.trace_id
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

            if turn.status == "waiting":
                self.event_bus.emit(
                    AgentWaitingEvent(
                        ctx=build_event_context(context.agent, context.trace_id),
                        waiting_for=list(context.agent.waiting_for),
                    )
                )
                return RunResult(ok=True, status="waiting", agent=context.agent)

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

    async def run_agent_stream(
        self,
        agent_id: str,
        *,
        max_turns: int = 10,
        last_agent_sequence: int = 0,
        trace_id: str | None = None,
    ) -> AsyncIterable[ProviderStreamEvent]:
        context = self.load_agent_context(
            agent_id,
            trace_id=trace_id,
            last_agent_sequence=last_agent_sequence,
        )
        if context.agent.status == AgentStatus.WAITING:
            return

        context.agent.trace_id = context.trace_id
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
                result = self._fail_run(context, error="Agent exceeded max_turns.")
                yield ProviderErrorEvent(error=result.error or "Agent exceeded max_turns.")
                return

            self.event_bus.emit(
                TurnStartedEvent(
                    ctx=build_event_context(context.agent, context.trace_id),
                    turn_count=context.agent.turn_count,
                )
            )

            resolved = self.provider_registry.resolve(context.agent.config.model)
            if resolved is None:
                turn_result = TurnResult(
                    status="failed",
                    agent=context.agent,
                    error=f"Unknown provider or model reference: {context.agent.config.model}",
                )
            else:
                request_input, request = self._build_provider_request(context, model=resolved.model)
                generation_started_at = utcnow()
                generation_timer_started_at = perf_counter()
                response: ProviderResponse | None = None
                turn_result = None

                try:
                    async for event in resolved.provider.stream(request):
                        yield event
                        if isinstance(event, ProviderDoneEvent):
                            response = event.response
                        elif isinstance(event, ProviderErrorEvent):
                            turn_result = TurnResult(
                                status="failed",
                                agent=context.agent,
                                error=event.error,
                                error_emitted=True,
                            )
                            break
                except Exception as exc:
                    turn_result = TurnResult(
                        status="failed",
                        agent=context.agent,
                        error=str(exc) or "Provider call failed.",
                    )

                if turn_result is None:
                    if response is None:
                        turn_result = TurnResult(
                            status="failed",
                            agent=context.agent,
                            error="Provider stream ended without a final response.",
                        )
                    else:
                        self._emit_generation_completed_event(
                            context,
                            model=resolved.model,
                            request=request,
                            response=response,
                            generation_started_at=generation_started_at,
                            generation_timer_started_at=generation_timer_started_at,
                        )
                        turn_result = await self.handle_turn_response(context, response)

            context.agent = turn_result.agent
            total_usage = self._add_usage(total_usage, turn_result.usage)

            if turn_result.status != "failed":
                self.event_bus.emit(
                    TurnCompletedEvent(
                        ctx=build_event_context(context.agent, context.trace_id),
                        turn_count=context.agent.turn_count,
                        usage=turn_result.usage,
                    )
                )

            context.agent.turn_count += 1
            context.agent.updated_at = utcnow()
            context.agent = self.agent_repository.save(context.agent)
            turns_executed += 1

            if turn_result.status == "continue":
                context = self.reload_context(context)
                continue

            if turn_result.status == "waiting":
                self.event_bus.emit(
                    AgentWaitingEvent(
                        ctx=build_event_context(context.agent, context.trace_id),
                        waiting_for=list(context.agent.waiting_for),
                    )
                )
                return

            if turn_result.status == "completed":
                self.event_bus.emit(
                    AgentCompletedEvent(
                        ctx=build_event_context(context.agent, context.trace_id),
                        duration_ms=self._duration_ms(run_started_at),
                        usage=total_usage,
                        result=self._find_run_result(context),
                    )
                )
                return

            result = self._fail_run(
                context,
                error=turn_result.error or "Agent execution failed.",
            )
            if not turn_result.error_emitted:
                yield ProviderErrorEvent(error=result.error or "Agent execution failed.")
            return

        result = self._fail_run(context, error="Agent stopped unexpectedly.")
        yield ProviderErrorEvent(error=result.error or "Agent stopped unexpectedly.")

    async def execute_turn(self, context: AgentRunContext) -> TurnResult:
        resolved = self.provider_registry.resolve(context.agent.config.model)
        if resolved is None:
            return TurnResult(
                status="failed",
                agent=context.agent,
                error=f"Unknown provider or model reference: {context.agent.config.model}",
            )

        _request_input, request = self._build_provider_request(context, model=resolved.model)
        generation_started_at = utcnow()
        generation_timer_started_at = perf_counter()

        try:
            response = await resolved.provider.generate(request)
        except Exception as exc:
            return TurnResult(status="failed", agent=context.agent, error=str(exc) or "Provider call failed.")

        self._emit_generation_completed_event(
            context,
            model=resolved.model,
            request=request,
            response=response,
            generation_started_at=generation_started_at,
            generation_timer_started_at=generation_timer_started_at,
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
            context.agent.waiting_for = []
            context.agent.status = AgentStatus.COMPLETED
            return TurnResult(status="completed", agent=context.agent, usage=response.usage)

        waiting_for: list[WaitingForEntry] = []

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
                handled = await self._handle_mcp_function_call(
                    context,
                    function_call=function_call,
                    tool_started_at=tool_started_at,
                    tool_timer_started_at=tool_timer_started_at,
                )
                if handled:
                    continue

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

            if tool.type == "sync":
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
                continue

            if tool.type == "human":
                result = await self.tool_registry.execute(function_call.name, function_call.arguments)
                duration_ms = self._duration_ms(tool_started_at, tool_timer_started_at)
                if not bool(result.get("ok")):
                    tool_output = self.store_tool_output(
                        context.agent,
                        context.session,
                        call_id=function_call.call_id,
                        name=function_call.name,
                        result=result,
                        is_error=True,
                    )
                    context.items.append(tool_output)
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
                    continue

                output = dict(result)
                self.event_bus.emit(
                    ToolCompletedEvent(
                        ctx=build_event_context(context.agent, context.trace_id),
                        call_id=function_call.call_id,
                        name=function_call.name,
                        arguments=function_call.arguments,
                        output=output,
                        duration_ms=duration_ms,
                        start_time=tool_started_at,
                    )
                )
                waiting_for.append(
                    WaitingForEntry(
                        call_id=function_call.call_id,
                        type="human",
                        name=function_call.name,
                        description=self._string_or_none(output.get("output")),
                        agent_id=context.agent.id,
                    )
                )
                continue

            if tool.type == "agent":
                result = await self.tool_registry.execute(function_call.name, function_call.arguments)
                duration_ms = self._duration_ms(tool_started_at, tool_timer_started_at)
                if not bool(result.get("ok")):
                    tool_output = self.store_tool_output(
                        context.agent,
                        context.session,
                        call_id=function_call.call_id,
                        name=function_call.name,
                        result=result,
                        is_error=True,
                    )
                    context.items.append(tool_output)
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
                    continue

                waiting_entry = await self._handle_agent_function_call(
                    context,
                    function_call=function_call,
                    tool_started_at=tool_started_at,
                    tool_timer_started_at=tool_timer_started_at,
                )
                if waiting_entry is not None:
                    waiting_for.append(waiting_entry)
                continue

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

        if waiting_for:
            context.agent.status = AgentStatus.WAITING
            context.agent.waiting_for = waiting_for
            return TurnResult(status="waiting", agent=context.agent, usage=response.usage)

        context.agent.waiting_for = []
        return TurnResult(status="continue", agent=context.agent, usage=response.usage)

    async def _handle_agent_function_call(
        self,
        context: AgentRunContext,
        *,
        function_call: ProviderFunctionCallOutputItem,
        tool_started_at: object,
        tool_timer_started_at: float,
    ) -> WaitingForEntry | None:
        agent_name = _require_non_empty_string(function_call.arguments.get("agent_name"), "agent_name")
        task = _require_non_empty_string(function_call.arguments.get("task"), "task")
        duration_ms = self._duration_ms(tool_started_at, tool_timer_started_at)

        if context.agent.depth + 1 > self.max_delegation_depth:
            error_message = f"Delegation depth exceeded max depth of {self.max_delegation_depth}."
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
                    duration_ms=duration_ms,
                    start_time=tool_started_at,
                )
            )
            return None

        try:
            loaded_agent = self.agent_loader.load_agent_by_name(agent_name)
        except Exception as exc:
            error_message = str(exc) or f"Child agent not found: {agent_name}"
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
                    duration_ms=duration_ms,
                    start_time=tool_started_at,
                )
            )
            return None

        child_agent = self._create_child_agent(
            parent_agent=context.agent,
            agent_name=loaded_agent.agent_name,
            model=loaded_agent.model or context.agent.config.model,
            task=loaded_agent.system_prompt,
            tools=loaded_agent.tools,
            source_call_id=function_call.call_id,
        )
        self._store_child_task(child_agent, context.session, task)

        child_result = await self.run_agent(
            child_agent.id,
            last_agent_sequence=0,
            trace_id=context.trace_id,
        )
        if child_result.status == "completed":
            output = {
                "ok": True,
                "output": self._find_agent_output_by_id(child_agent.id),
            }
            tool_output = self.store_tool_output(
                context.agent,
                context.session,
                call_id=function_call.call_id,
                name=function_call.name,
                result=output,
                is_error=False,
            )
            context.items.append(tool_output)
            self.event_bus.emit(
                ToolCompletedEvent(
                    ctx=build_event_context(context.agent, context.trace_id),
                    call_id=function_call.call_id,
                    name=function_call.name,
                    arguments=function_call.arguments,
                    output=output,
                    duration_ms=duration_ms,
                    start_time=tool_started_at,
                )
            )
            return None

        if child_result.status == "waiting":
            waiting_description = self._describe_waiting(child_result.agent) or task
            waiting_entry = WaitingForEntry(
                call_id=function_call.call_id,
                type="agent",
                name=function_call.name,
                description=waiting_description,
                agent_id=child_agent.id,
            )
            self.event_bus.emit(
                ToolCompletedEvent(
                    ctx=build_event_context(context.agent, context.trace_id),
                    call_id=function_call.call_id,
                    name=function_call.name,
                    arguments=function_call.arguments,
                    output={"ok": True, "output": waiting_entry.description or task},
                    duration_ms=duration_ms,
                    start_time=tool_started_at,
                )
            )
            return waiting_entry

        error_message = child_result.error or "Delegated agent execution failed."
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
                duration_ms=duration_ms,
                start_time=tool_started_at,
            )
        )
        return None

    async def _handle_mcp_function_call(
        self,
        context: AgentRunContext,
        *,
        function_call: ProviderFunctionCallOutputItem,
        tool_started_at: object,
        tool_timer_started_at: float,
    ) -> bool:
        if self.mcp_manager.parse_name(function_call.name) is None:
            return False

        try:
            output = await self.mcp_manager.call_tool(
                function_call.name,
                function_call.arguments,
            )
            result: dict[str, Any] = {"ok": True, "output": output}
            is_error = False
        except Exception as exc:
            result = {"ok": False, "error": str(exc) or "MCP tool execution failed."}
            is_error = True

        tool_output = self.store_tool_output(
            context.agent,
            context.session,
            call_id=function_call.call_id,
            name=function_call.name,
            result=result,
            is_error=is_error,
        )
        context.items.append(tool_output)

        duration_ms = self._duration_ms(tool_started_at, tool_timer_started_at)
        if is_error:
            self.event_bus.emit(
                ToolFailedEvent(
                    ctx=build_event_context(context.agent, context.trace_id),
                    call_id=function_call.call_id,
                    name=function_call.name,
                    arguments=function_call.arguments,
                    error=str(result.get("error") or "MCP tool execution failed."),
                    duration_ms=duration_ms,
                    start_time=tool_started_at,
                )
            )
            return True

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
        return True

    def load_agent_context(
        self,
        agent_id: str,
        *,
        trace_id: str | None,
        last_agent_sequence: int,
    ) -> AgentRunContext:
        agent = self.agent_repository.get(agent_id)
        if agent is None:
            raise RuntimeError(f"Agent not found: {agent_id}")

        session = self.session_repository.get(agent.session_id)
        if session is None:
            raise RuntimeError(f"Session not found for agent: {agent_id}")

        items = self.item_repository.list_by_agent(agent.id)
        resolved_trace_id = trace_id or agent.trace_id or uuid4().hex
        return AgentRunContext(
            agent=agent,
            session=session,
            items=items,
            trace_id=resolved_trace_id,
            last_agent_sequence=last_agent_sequence,
        )

    def reload_context(self, context: AgentRunContext) -> AgentRunContext:
        return self.load_agent_context(
            context.agent.id,
            trace_id=context.trace_id,
            last_agent_sequence=context.last_agent_sequence,
        )

    async def deliver_result(
        self,
        agent_id: str,
        *,
        call_id: str,
        result: dict[str, Any],
        trace_id: str | None = None,
    ) -> RunResult:
        context = self.load_agent_context(
            agent_id,
            trace_id=trace_id,
            last_agent_sequence=0,
        )
        if context.agent.status != AgentStatus.WAITING:
            return RunResult(
                ok=False,
                status="failed",
                agent=context.agent,
                error="Agent is not waiting for input.",
            )

        waiting_entry = next((entry for entry in context.agent.waiting_for if entry.call_id == call_id), None)
        if waiting_entry is None:
            return RunResult(
                ok=False,
                status="failed",
                agent=context.agent,
                error=f"Waiting call not found: {call_id}",
            )

        if waiting_entry.type == "agent":
            child_agent = self.agent_repository.get_child_by_source_call(context.agent.id, call_id)
            if child_agent is None:
                return RunResult(
                    ok=False,
                    status="failed",
                    agent=context.agent,
                    error=f"Delegated child agent not found for call: {call_id}",
                )
            if len(child_agent.waiting_for) != 1:
                return RunResult(
                    ok=False,
                    status="failed",
                    agent=context.agent,
                    error="Delegated agent is waiting on multiple inputs; delivery is ambiguous.",
                )

            delegated_result = await self.deliver_result(
                child_agent.id,
                call_id=child_agent.waiting_for[0].call_id,
                result=result,
                trace_id=context.trace_id,
            )
            if not delegated_result.ok:
                return delegated_result
            refreshed_agent = self.agent_repository.get(agent_id)
            if refreshed_agent is None:
                return RunResult(ok=False, status="failed", error=f"Agent disappeared during delivery: {agent_id}")
            return self._build_run_result_from_agent(refreshed_agent)

        last_sequence = self.item_repository.get_last_sequence(context.agent.id)
        tool_output = self.store_tool_output(
            context.agent,
            context.session,
            call_id=call_id,
            name=waiting_entry.name,
            result=result,
            is_error=not bool(result.get("ok")),
        )
        context.items.append(tool_output)
        context.agent.waiting_for = [entry for entry in context.agent.waiting_for if entry.call_id != call_id]
        context.agent.updated_at = utcnow()
        self.event_bus.emit(
            AgentResumedEvent(
                ctx=build_event_context(context.agent, context.trace_id),
                call_id=call_id,
                waiting_for=list(context.agent.waiting_for),
            )
        )

        if context.agent.waiting_for:
            context.agent.status = AgentStatus.WAITING
            context.agent.trace_id = context.trace_id
            context.agent = self.agent_repository.save(context.agent)
            return RunResult(ok=True, status="waiting", agent=context.agent)

        context.agent.trace_id = context.trace_id
        context.agent.status = AgentStatus.PENDING
        context.agent = self.agent_repository.save(context.agent)
        run_result = await self.run_agent(
            context.agent.id,
            last_agent_sequence=last_sequence,
            trace_id=context.trace_id,
        )
        if run_result.agent is not None:
            await self._propagate_child_result(run_result.agent, run_result, trace_id=context.trace_id)
        return run_result

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

    def _create_child_agent(
        self,
        *,
        parent_agent: Agent,
        agent_name: str,
        model: str,
        task: str,
        tools: list[Any],
        source_call_id: str,
    ) -> Agent:
        now = utcnow()
        child = Agent(
            id=uuid4().hex,
            session_id=parent_agent.session_id,
            trace_id=parent_agent.trace_id,
            root_agent_id=parent_agent.root_agent_id,
            parent_id=parent_agent.id,
            source_call_id=source_call_id,
            depth=parent_agent.depth + 1,
            agent_name=agent_name,
            status=AgentStatus.PENDING,
            turn_count=0,
            waiting_for=[],
            config=AgentConfig(
                model=model,
                task=task,
                tools=tools,
                temperature=parent_agent.config.temperature,
            ),
            created_at=now,
            updated_at=now,
        )
        return self.agent_repository.save(child)

    def _store_child_task(self, child_agent: Agent, session: Session, task: str) -> Item:
        item = Item(
            id=uuid4().hex,
            session_id=session.id,
            agent_id=child_agent.id,
            sequence=1,
            type=ItemType.MESSAGE,
            role=MessageRole.USER,
            content=task,
            call_id=None,
            name=None,
            arguments_json=None,
            output=None,
            is_error=False,
            created_at=utcnow(),
        )
        return self.item_repository.save(item)

    async def _propagate_child_result(self, agent: Agent, run_result: RunResult, *, trace_id: str | None = None) -> None:
        if agent.parent_id is None or agent.source_call_id is None:
            return
        if run_result.status == "waiting":
            return

        parent_agent = self.agent_repository.get(agent.parent_id)
        if parent_agent is None:
            return
        resolved_trace_id = trace_id or agent.trace_id or parent_agent.trace_id or uuid4().hex

        waiting_entry = next((entry for entry in parent_agent.waiting_for if entry.call_id == agent.source_call_id), None)
        if waiting_entry is None:
            return

        session = self.session_repository.get(parent_agent.session_id)
        if session is None:
            return

        last_sequence = self.item_repository.get_last_sequence(parent_agent.id)
        result_payload: dict[str, Any]
        is_error: bool
        if run_result.ok:
            result_payload = {"ok": True, "output": self._find_agent_output_by_id(agent.id)}
            is_error = False
        else:
            result_payload = {"ok": False, "error": run_result.error or "Delegated agent execution failed."}
            is_error = True

        self.store_tool_output(
            parent_agent,
            session,
            call_id=agent.source_call_id,
            name=waiting_entry.name,
            result=result_payload,
            is_error=is_error,
        )
        parent_agent.waiting_for = [
            entry for entry in parent_agent.waiting_for if entry.call_id != agent.source_call_id
        ]
        parent_agent.updated_at = utcnow()
        self.event_bus.emit(
            AgentResumedEvent(
                ctx=build_event_context(parent_agent, resolved_trace_id),
                call_id=agent.source_call_id,
                waiting_for=list(parent_agent.waiting_for),
            )
        )

        if parent_agent.waiting_for:
            parent_agent.status = AgentStatus.WAITING
            parent_agent.trace_id = resolved_trace_id
            self.agent_repository.save(parent_agent)
            return

        parent_agent.trace_id = resolved_trace_id
        parent_agent.status = AgentStatus.PENDING
        self.agent_repository.save(parent_agent)
        parent_result = await self.run_agent(
            parent_agent.id,
            last_agent_sequence=last_sequence,
            trace_id=resolved_trace_id,
        )
        if parent_result.agent is not None:
            await self._propagate_child_result(parent_result.agent, parent_result, trace_id=resolved_trace_id)

    @staticmethod
    def _deserialize_arguments(raw_arguments: str | None) -> dict[str, Any]:
        if not raw_arguments:
            return {}
        try:
            payload = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _find_agent_output_by_id(self, agent_id: str) -> str | None:
        result: str | None = None
        for item in self.item_repository.list_by_agent(agent_id):
            if item.type == ItemType.MESSAGE and item.role == MessageRole.ASSISTANT and item.content:
                result = item.content
        return result

    @staticmethod
    def _string_or_none(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return str(value)

    @staticmethod
    def _describe_waiting(agent: Agent | None) -> str | None:
        if agent is None:
            return None
        descriptions = [entry.description for entry in agent.waiting_for if entry.description]
        if not descriptions:
            return None
        return " | ".join(descriptions)

    def _build_run_result_from_agent(self, agent: Agent) -> RunResult:
        if agent.status == AgentStatus.WAITING:
            return RunResult(ok=True, status="waiting", agent=agent)
        if agent.status == AgentStatus.COMPLETED:
            return RunResult(ok=True, status="completed", agent=agent)
        if agent.status == AgentStatus.FAILED:
            return RunResult(ok=False, status="failed", agent=agent, error="Agent execution failed.")
        return RunResult(ok=False, status="failed", agent=agent, error=f"Unexpected agent status: {agent.status}")

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

    def _emit_generation_completed_event(
        self,
        context: AgentRunContext,
        *,
        model: str,
        request: ProviderRequest,
        response: ProviderResponse,
        generation_started_at: object,
        generation_timer_started_at: float,
    ) -> None:
        self.event_bus.emit(
            GenerationCompletedEvent(
                ctx=build_event_context(context.agent, context.trace_id),
                model=model,
                instructions=request.instructions,
                input=request.input,
                output=response.output,
                usage=response.usage,
                duration_ms=self._duration_ms(generation_started_at, generation_timer_started_at),
                start_time=generation_started_at,
            )
        )

    def _build_provider_request(
        self,
        context: AgentRunContext,
        *,
        model: str,
    ) -> tuple[
        list[ProviderMessageInputItem | ProviderFunctionCallInputItem | ProviderFunctionCallOutputInputItem],
        ProviderRequest,
    ]:
        request_input = self.map_items_to_provider_input(context.items)
        request = ProviderRequest(
            model=model,
            instructions=context.agent.config.task,
            input=request_input,
            tools=context.agent.config.tools or [],
            temperature=context.agent.config.temperature,
        )
        return request_input, request

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
