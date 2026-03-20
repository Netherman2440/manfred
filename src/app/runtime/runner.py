from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.db.repositories.agent_repository import AgentRepository
from app.db.repositories.item_repository import ItemRepository
from app.db.repositories.session_repository import SessionRepository
from app.domain import (
    Agent,
    FunctionToolDefinition,
    Item,
    ItemType,
    MessageRole,
    ProviderFunctionCall,
    ProviderFunctionCallInput,
    ProviderFunctionResultInput,
    ProviderInput,
    ProviderMessageInput,
    ProviderResponse,
    ProviderTextOutput,
    Session,
    ToolRegistry,
    complete_agent,
    fail_agent,
    increment_agent_turn,
    start_agent,
)
from app.domain.provider import Provider
from app.services.observability import ObservabilityService


@dataclass(slots=True, frozen=True)
class TurnResult:
    agent: Agent
    continue_loop: bool


@dataclass(slots=True, frozen=True)
class RunResult:
    agent: Agent
    status: str
    error: str | None = None


class AgentRunner:
    def __init__(
        self,
        *,
        agent_repository: AgentRepository,
        session_repository: SessionRepository,
        item_repository: ItemRepository,
        tool_registry: ToolRegistry,
        provider: Provider,
        observability: ObservabilityService,
        max_turn_count: int,
    ) -> None:
        self._agent_repository = agent_repository
        self._session_repository = session_repository
        self._item_repository = item_repository
        self._tool_registry = tool_registry
        self._provider = provider
        self._observability = observability
        self._max_turn_count = max_turn_count

    async def run_agent(self, agent_id: str) -> RunResult:
        agent = self._agent_repository.get_by_id(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} does not exist.")

        session = self._session_repository.get_by_id(agent.session_id)
        if session is None:
            raise ValueError(f"Session {agent.session_id} does not exist.")

        # TODO: Add execution context once agent runtime grows beyond single-agent chat.
        # TODO: Replace this with explicit start/resume/status handling.
        agent = self._agent_repository.update(start_agent(agent))

        turn_index = 0
        while turn_index < self._max_turn_count:
            try:
                turn_result = await self.execute_turn(agent, session)
            except Exception as exc:  # noqa: BLE001
                error_message = str(exc) or "Turn execution failed."
                self._observability.update_current_span(
                    level="ERROR",
                    status_message=error_message,
                )
                self._observability.record_error(
                    name="agent.run.failed",
                    error=error_message,
                    metadata={"agent_id": agent.id, "session_id": session.id},
                )
                failed_agent = self._agent_repository.update(fail_agent(agent))
                return RunResult(
                    agent=failed_agent,
                    status="failed",
                    error=error_message,
                )

            agent = turn_result.agent

            if not turn_result.continue_loop:
                status = "failed" if agent.status.value == "failed" else "completed"
                return RunResult(agent=agent, status=status)

            turn_index += 1

        failed_agent = self._agent_repository.update(fail_agent(agent))
        return RunResult(
            agent=failed_agent,
            status="failed",
            error=f"Max turn count exceeded ({self._max_turn_count}).",
        )

    async def execute_turn(self, agent: Agent, session: Session) -> TurnResult:
        items = self._item_repository.list_by_agent(agent.id)

        # TODO: Add pruning and summarization before calling the provider.
        provider_input = ProviderInput(
            model=agent.config.model,
            instructions=agent.config.task,
            items=self._map_items_to_provider_input(items),
            tools=self._resolve_function_tools(agent),
        )
        with self._observability.start_generation(
            model=provider_input.model,
            input_payload=self._serialize_provider_input(provider_input),
            metadata={
                "agent_id": agent.id,
                "item_count": len(provider_input.items),
                "tool_count": len(provider_input.tools),
            },
        ):
            try:
                response = self._provider.generate(provider_input)
            except Exception as exc:
                error_message = str(exc) or "Provider request failed."
                self._observability.update_current_generation(
                    level="ERROR",
                    status_message=error_message,
                )
                self._observability.record_error(
                    name="llm.generate.failed",
                    error=error_message,
                    metadata={"agent_id": agent.id, "session_id": session.id},
                )
                raise

            self._observability.update_current_generation(
                output=self._serialize_provider_response(response),
            )

        turn_result = await self.handle_turn_response(agent, session, response)
        updated_agent = self._agent_repository.update(increment_agent_turn(turn_result.agent))
        return TurnResult(agent=updated_agent, continue_loop=turn_result.continue_loop)

    async def handle_turn_response(
        self,
        agent: Agent,
        session: Session,
        response: ProviderResponse,
    ) -> TurnResult:
        sequence = self._item_repository.get_last_sequence(agent.id)
        function_calls: list[ProviderFunctionCall] = []

        for output_item in response.output:
            sequence += 1
            if isinstance(output_item, ProviderTextOutput):
                item = self._item_repository.create(
                    session_id=session.id,
                    agent_id=agent.id,
                    sequence=sequence,
                    item_type=ItemType.MESSAGE,
                    role=MessageRole.ASSISTANT,
                    content=output_item.text,
                )
                self._observability.record_item(item)
                continue

            if isinstance(output_item, ProviderFunctionCall):
                item = self._item_repository.create(
                    session_id=session.id,
                    agent_id=agent.id,
                    sequence=sequence,
                    item_type=ItemType.FUNCTION_CALL,
                    call_id=output_item.call_id,
                    name=output_item.name,
                    arguments_json=json.dumps(output_item.arguments),
                )
                self._observability.record_item(item)
                function_calls.append(output_item)

        if not function_calls:
            return TurnResult(agent=complete_agent(agent), continue_loop=False)

        for function_call in function_calls:
            with self._observability.start_tool_execution(
                name=function_call.name,
                call_id=function_call.call_id,
                input_payload=function_call.arguments,
            ):
                tool = self._tool_registry.get(function_call.name)
                if tool is None:
                    tool_result = {"ok": False, "error": f"Tool not found: {function_call.name}"}
                elif tool.type != "sync":
                    tool_result = {
                        "ok": False,
                        "error": f"Unsupported tool type: {tool.type}",
                    }
                else:
                    tool_result = await self._tool_registry.execute(
                        function_call.name,
                        function_call.arguments,
                        call_id=function_call.call_id,
                    )

                self._observability.update_current_span(
                    output=tool_result,
                    level="ERROR" if not bool(tool_result.get("ok")) else None,
                    status_message=str(tool_result.get("error")) if tool_result.get("error") is not None else None,
                )

            sequence += 1
            item = self._item_repository.create(
                session_id=session.id,
                agent_id=agent.id,
                sequence=sequence,
                item_type=ItemType.FUNCTION_CALL_OUTPUT,
                call_id=function_call.call_id,
                name=function_call.name,
                output=self._serialize_tool_result_output(tool_result),
                is_error=not bool(tool_result.get("ok")),
            )
            self._observability.record_item(item)

        return TurnResult(agent=agent, continue_loop=True)

    def _map_items_to_provider_input(self, items: list[Item]) -> list[ProviderMessageInput | ProviderFunctionCallInput | ProviderFunctionResultInput]:
        mapped_items: list[ProviderMessageInput | ProviderFunctionCallInput | ProviderFunctionResultInput] = []

        for item in items:
            if item.type == ItemType.MESSAGE and item.role is not None and item.content is not None:
                mapped_items.append(
                    ProviderMessageInput(
                        role=item.role.value,
                        content=item.content,
                    )
                )
                continue

            if item.type == ItemType.FUNCTION_CALL and item.call_id and item.name:
                mapped_items.append(
                    ProviderFunctionCallInput(
                        call_id=item.call_id,
                        name=item.name,
                        arguments=self._parse_arguments(item.arguments_json),
                    )
                )
                continue

            if item.type == ItemType.FUNCTION_CALL_OUTPUT and item.call_id and item.name and item.output is not None:
                mapped_items.append(
                    ProviderFunctionResultInput(
                        call_id=item.call_id,
                        name=item.name,
                        output=self._deserialize_tool_output(item.output),
                        is_error=item.is_error,
                    )
                )

        return mapped_items

    def _resolve_function_tools(self, agent: Agent) -> list[FunctionToolDefinition]:
        resolved_tools: list[FunctionToolDefinition] = []
        for tool_name in agent.config.tool_names:
            tool = self._tool_registry.get(tool_name)
            if tool is not None:
                resolved_tools.append(tool.definition)
        return resolved_tools

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
    def _serialize_tool_result_output(tool_result: dict[str, Any]) -> str:
        if tool_result.get("ok"):
            output = tool_result.get("output")
            return AgentRunner._serialize_tool_output(output)

        error = tool_result.get("error")
        return str(error) if error is not None else "Tool execution failed."

    @staticmethod
    def _serialize_tool_output(output: Any) -> str:
        if isinstance(output, str):
            return output
        return json.dumps(output, ensure_ascii=False)

    @staticmethod
    def _deserialize_tool_output(output: str) -> Any:
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return output

    @staticmethod
    def _serialize_provider_input(provider_input: ProviderInput) -> dict[str, Any]:
        return {
            "model": provider_input.model,
            "instructions": provider_input.instructions,
            "items": [AgentRunner._serialize_provider_item(item) for item in provider_input.items],
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
                for tool in provider_input.tools
            ],
        }

    @staticmethod
    def _serialize_provider_item(
        item: ProviderMessageInput | ProviderFunctionCallInput | ProviderFunctionResultInput,
    ) -> dict[str, Any]:
        if isinstance(item, ProviderMessageInput):
            return {
                "type": item.type,
                "role": item.role,
                "content": item.content,
            }

        if isinstance(item, ProviderFunctionCallInput):
            return {
                "type": item.type,
                "call_id": item.call_id,
                "name": item.name,
                "arguments": item.arguments,
            }

        return {
            "type": item.type,
            "call_id": item.call_id,
            "name": item.name,
            "output": item.output,
            "is_error": item.is_error,
        }

    @staticmethod
    def _serialize_provider_response(response: ProviderResponse) -> dict[str, Any]:
        output: list[dict[str, Any]] = []
        for item in response.output:
            if isinstance(item, ProviderTextOutput):
                output.append({"type": item.type, "text": item.text})
                continue

            output.append(
                {
                    "type": item.type,
                    "call_id": item.call_id,
                    "name": item.name,
                    "arguments": item.arguments,
                }
            )

        return {"output": output}
