from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from app.db.base import utcnow
from app.domain import Agent, AgentStatus, Item, ItemType, MessageRole, Session
from app.domain.repositories import AgentRepository, ItemRepository, SessionRepository
from app.providers import (
    ProviderFunctionCallInputItem,
    ProviderFunctionCallOutputInputItem,
    ProviderFunctionCallOutputItem,
    ProviderMessageInputItem,
    ProviderRegistry,
    ProviderRequest,
    ProviderResponse,
    ProviderTextOutputItem,
)
from app.tools.registry import ToolRegistry


@dataclass(slots=True)
class AgentRunContext:
    agent: Agent
    session: Session
    items: list[Item]


@dataclass(slots=True)
class TurnResult:
    status: Literal["continue", "completed", "failed"]
    agent: Agent
    error: str | None = None


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
    ) -> None:
        self.agent_repository = agent_repository
        self.session_repository = session_repository
        self.item_repository = item_repository
        self.tool_registry = tool_registry
        self.provider_registry = provider_registry

    async def run_agent(self, agent_id: str, *, max_turns: int = 10) -> RunResult:
        context = self.load_agent_context(agent_id)
        if context.agent.status == AgentStatus.WAITING:
            return RunResult(ok=False, status="failed", error="Waiting agents are not implemented yet.")

        context.agent.status = AgentStatus.RUNNING
        context.agent.updated_at = utcnow()
        self.agent_repository.save(context.agent)

        turns_executed = 0

        while context.agent.status == AgentStatus.RUNNING:
            if turns_executed >= max_turns:
                context.agent.status = AgentStatus.FAILED
                context.agent.updated_at = utcnow()
                self.agent_repository.save(context.agent)
                return RunResult(ok=False, status="failed", agent=context.agent, error="Agent exceeded max_turns.")

            turn = await self.execute_turn(context)
            context.agent = turn.agent
            context.agent.turn_count += 1
            context.agent.updated_at = utcnow()
            self.agent_repository.save(context.agent)
            turns_executed += 1

            if turn.status == "continue":
                context = self.reload_context(context.agent.id)
                continue

            if turn.status == "completed":
                return RunResult(ok=True, status="completed", agent=context.agent)

            context.agent.status = AgentStatus.FAILED
            context.agent.updated_at = utcnow()
            self.agent_repository.save(context.agent)
            return RunResult(
                ok=False,
                status="failed",
                agent=context.agent,
                error=turn.error or "Agent execution failed.",
            )

        return RunResult(ok=False, status="failed", agent=context.agent, error="Agent stopped unexpectedly.")

    async def execute_turn(self, context: AgentRunContext) -> TurnResult:
        resolved = self.provider_registry.resolve(context.agent.config.model)
        if resolved is None:
            return TurnResult(
                status="failed",
                agent=context.agent,
                error=f"Unknown provider or model reference: {context.agent.config.model}",
            )

        request = ProviderRequest(
            model=resolved.model,
            instructions=context.agent.config.task,
            input=self.map_items_to_provider_input(context.items),
            tools=context.agent.config.tools or [],
            temperature=context.agent.config.temperature,
        )

        try:
            response = await resolved.provider.generate(request)
        except Exception as exc: 
            return TurnResult(status="failed", agent=context.agent, error=str(exc) or "Provider call failed.")

        return await self.handle_turn_response(context, response)

    async def handle_turn_response(
        self,
        context: AgentRunContext,
        response: ProviderResponse,
    ) -> TurnResult:
        self.store_provider_output(context.agent, context.session, response)

        function_calls = [
            output_item
            for output_item in response.output
            if isinstance(output_item, ProviderFunctionCallOutputItem)
        ]

        if not function_calls: #TODO what with reasoning?
            context.agent.status = AgentStatus.COMPLETED
            return TurnResult(status="completed", agent=context.agent)

        for function_call in function_calls:
            tool = self.tool_registry.get(function_call.name)
            if tool is None:
                self.store_tool_output(
                    context.agent,
                    context.session,
                    call_id=function_call.call_id,
                    name=function_call.name,
                    result={"ok": False, "error": f"Tool not found: {function_call.name}"},
                    is_error=True,
                )
                continue

            if tool.type != "sync":
                return TurnResult(
                    status="failed",
                    agent=context.agent,
                    error=f"Tool type '{tool.type}' is not implemented yet.",
                )

            result = await self.tool_registry.execute(function_call.name, function_call.arguments)
            self.store_tool_output(
                context.agent,
                context.session,
                call_id=function_call.call_id,
                name=function_call.name,
                result=result,
                is_error=not bool(result.get("ok")),
            )

        return TurnResult(status="continue", agent=context.agent)

    def load_agent_context(self, agent_id: str) -> AgentRunContext:
        agent = self.agent_repository.get(agent_id)
        if agent is None:
            raise RuntimeError(f"Agent not found: {agent_id}")

        session = self.session_repository.get(agent.session_id)
        if session is None:
            raise RuntimeError(f"Session not found for agent: {agent_id}")

        items = self.item_repository.list_by_agent(agent.id)
        return AgentRunContext(agent=agent, session=session, items=items)

    def reload_context(self, agent_id: str) -> AgentRunContext:
        return self.load_agent_context(agent_id)

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
