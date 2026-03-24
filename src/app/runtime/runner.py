from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

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
    WaitingFor,
    complete_agent,
    deliver_one,
    fail_agent,
    increment_agent_turn,
    start_agent,
    tool_error,
    tool_ok,
    wait_for_many,
)
from app.domain.provider import Provider
from app.services.observability import ObservabilityService
from app.workspace import AgentTemplateLoader


@dataclass(slots=True, frozen=True)
class TurnResult:
    agent: Agent
    outcome: Literal["continue", "completed", "waiting", "failed"]


@dataclass(slots=True, frozen=True)
class RunResult:
    agent: Agent
    status: Literal["completed", "waiting", "failed", "cancelled"]
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
        subagent_max_turn_count: int,
        max_agent_depth: int,
        agent_template_loader: AgentTemplateLoader,
    ) -> None:
        self._agent_repository = agent_repository
        self._session_repository = session_repository
        self._item_repository = item_repository
        self._tool_registry = tool_registry
        self._provider = provider
        self._observability = observability
        self._max_turn_count = max_turn_count
        self._subagent_max_turn_count = subagent_max_turn_count
        self._max_agent_depth = max_agent_depth
        self._agent_template_loader = agent_template_loader

    async def run_agent(self, agent_id: str, *, max_turn_count: int | None = None) -> RunResult:
        agent = self._get_agent(agent_id)
        session = self._get_session(agent.session_id)
        limit = max_turn_count or self._max_turn_count

        if agent.status.value == "pending":
            agent = self._agent_repository.update(start_agent(agent))
            # TODO: emit agent.started event here.
        elif agent.status.value == "waiting":
            return RunResult(agent=agent, status="waiting")
        elif agent.status.value == "failed":
            return RunResult(agent=agent, status="failed", error=agent.error)
        elif agent.status.value == "cancelled":
            return RunResult(agent=agent, status="cancelled", error=agent.error)
        elif agent.status.value == "completed":
            return RunResult(agent=agent, status="completed")

        turn_index = 0
        while agent.status.value == "running" and turn_index < limit:
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
                failed_agent = self._agent_repository.update(fail_agent(agent, error=error_message))
                return RunResult(
                    agent=failed_agent,
                    status="failed",
                    error=error_message,
                )

            agent = turn_result.agent
            turn_index += 1

            if turn_result.outcome == "continue":
                continue
            if turn_result.outcome == "waiting":
                return RunResult(agent=agent, status="waiting")
            if turn_result.outcome == "failed":
                return RunResult(agent=agent, status="failed", error=agent.error)
            return RunResult(agent=agent, status="completed")

        if agent.status.value == "running":
            error_message = f"Max turn count exceeded ({limit})."
            failed_agent = self._agent_repository.update(fail_agent(agent, error=error_message))
            return RunResult(
                agent=failed_agent,
                status="failed",
                error=error_message,
            )

        if agent.status.value == "waiting":
            return RunResult(agent=agent, status="waiting")
        if agent.status.value == "failed":
            return RunResult(agent=agent, status="failed", error=agent.error)
        if agent.status.value == "cancelled":
            return RunResult(agent=agent, status="cancelled", error=agent.error)
        return RunResult(agent=agent, status="completed")

    async def deliver_result(
        self,
        *,
        agent_id: str,
        call_id: str,
        output: Any,
        is_error: bool,
    ) -> RunResult:
        agent = self._get_agent(agent_id)
        session = self._get_session(agent.session_id)
        wait = next((entry for entry in agent.waiting_for if entry.call_id == call_id), None)
        if wait is None:
            raise ValueError(f"Agent {agent_id} is not waiting for call_id '{call_id}'.")

        function_call = self._item_repository.find_function_call(agent.id, call_id)
        sequence = self._item_repository.get_last_sequence(agent.id) + 1
        item = self._item_repository.create(
            session_id=session.id,
            agent_id=agent.id,
            sequence=sequence,
            item_type=ItemType.FUNCTION_CALL_OUTPUT,
            call_id=call_id,
            name=function_call.name if function_call and function_call.name else wait.name,
            output=self._serialize_tool_output(output),
            is_error=is_error,
        )
        self._observability.record_item(item)

        updated_agent = self._agent_repository.update(deliver_one(agent, call_id))
        if updated_agent.status.value == "waiting":
            return RunResult(agent=updated_agent, status="waiting")

        # TODO: emit agent.resumed event here.
        run_result = await self.run_agent(agent_id)
        await self._maybe_propagate_to_parent(run_result)
        return run_result

    async def execute_turn(self, agent: Agent, session: Session) -> TurnResult:
        items = self._item_repository.list_by_agent(agent.id)

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
        return TurnResult(agent=updated_agent, outcome=turn_result.outcome)

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
            completed_agent = self._agent_repository.update(
                complete_agent(agent, result=self._extract_completion_result(response))
            )
            return TurnResult(agent=completed_agent, outcome="completed")

        waiting_for: list[WaitingFor] = []
        for function_call in function_calls:
            with self._observability.start_tool_execution(
                name=function_call.name,
                call_id=function_call.call_id,
                input_payload=function_call.arguments,
            ):
                tool = self._tool_registry.get(function_call.name)
                if tool is None:
                    tool_result = tool_error(
                        f"Tool not found: {function_call.name}",
                        hint="Użyj jednej z dostępnych definicji tooli przekazanych w kontekście.",
                        details={"tool": function_call.name},
                        retryable=False,
                    )
                    sequence = self._record_function_result(
                        session_id=session.id,
                        agent_id=agent.id,
                        sequence=sequence,
                        call_id=function_call.call_id,
                        name=function_call.name,
                        output=self._serialize_tool_result_output(function_call.name, tool_result),
                        is_error=True,
                    )
                    self._observability.update_current_span(
                        output=tool_result,
                        level="ERROR",
                        status_message=str(tool_result.get("error")),
                    )
                    continue

                if function_call.name == "send_message":
                    tool_result = await self._handle_send_message(agent, function_call)
                    sequence = self._record_function_result(
                        session_id=session.id,
                        agent_id=agent.id,
                        sequence=sequence,
                        call_id=function_call.call_id,
                        name=function_call.name,
                        output=self._serialize_tool_result_output(function_call.name, tool_result),
                        is_error=not bool(tool_result.get("ok")),
                    )
                    self._observability.update_current_span(
                        output=tool_result,
                        level="ERROR" if not bool(tool_result.get("ok")) else None,
                        status_message=str(tool_result.get("error")) if tool_result.get("error") is not None else None,
                    )
                    # TODO: emit tool.completed event here.
                    continue

                if tool.type == "sync":
                    tool_result = await self._tool_registry.execute(
                        function_call.name,
                        function_call.arguments,
                        call_id=function_call.call_id,
                    )
                    sequence = self._record_function_result(
                        session_id=session.id,
                        agent_id=agent.id,
                        sequence=sequence,
                        call_id=function_call.call_id,
                        name=function_call.name,
                        output=self._serialize_tool_result_output(function_call.name, tool_result),
                        is_error=not bool(tool_result.get("ok")),
                    )
                    self._observability.update_current_span(
                        output=tool_result,
                        level="ERROR" if not bool(tool_result.get("ok")) else None,
                        status_message=str(tool_result.get("error")) if tool_result.get("error") is not None else None,
                    )
                    # TODO: emit tool.completed event here.
                    continue

                if tool.type == "agent":
                    delegation_result = await self._handle_delegation(agent, function_call)
                    if delegation_result["status"] == "waiting":
                        waiting_for.append(delegation_result["waiting_for"])
                    else:
                        sequence = self._record_function_result(
                            session_id=session.id,
                            agent_id=agent.id,
                            sequence=sequence,
                            call_id=function_call.call_id,
                            name=function_call.name,
                            output=self._serialize_tool_output(delegation_result["output"]),
                            is_error=delegation_result["is_error"],
                        )
                    self._observability.update_current_span(
                        output=delegation_result,
                        level="ERROR" if delegation_result.get("is_error") else None,
                        status_message=(
                            str(delegation_result.get("output"))
                            if delegation_result.get("is_error")
                            else None
                        ),
                    )
                    continue

                waiting_for.append(
                    WaitingFor(
                        call_id=function_call.call_id,
                        type="human" if tool.type == "human" else "tool",
                        name=function_call.name,
                        description=tool.definition.description,
                    )
                )
                self._observability.update_current_span(output={"waiting_for": waiting_for[-1].name})

        if waiting_for:
            # TODO: emit agent.waiting event here.
            waiting_agent = self._agent_repository.update(wait_for_many(agent, waiting_for))
            return TurnResult(agent=waiting_agent, outcome="waiting")

        return TurnResult(agent=agent, outcome="continue")

    async def _handle_delegation(
        self,
        parent: Agent,
        function_call: ProviderFunctionCall,
    ) -> dict[str, object]:
        agent_name = function_call.arguments.get("agent")
        task = function_call.arguments.get("task")
        if not isinstance(agent_name, str) or agent_name.strip() == "":
            return {"status": "failed", "output": "delegate expects a non-empty 'agent' string.", "is_error": True}
        if not isinstance(task, str) or task.strip() == "":
            return {"status": "failed", "output": "delegate expects a non-empty 'task' string.", "is_error": True}
        if parent.depth + 1 > self._max_agent_depth:
            return {
                "status": "failed",
                "output": f"Max agent depth exceeded ({self._max_agent_depth}).",
                "is_error": True,
            }

        try:
            template = self._agent_template_loader.load(agent_name.strip())
        except ValueError as exc:
            return {
                "status": "failed",
                "output": str(exc),
                "is_error": True,
            }
        child = self._agent_repository.create(
            session_id=parent.session_id,
            config=template.to_agent_config(),
            root_agent_id=parent.root_agent_id,
            parent_id=parent.id,
            source_call_id=function_call.call_id,
            depth=parent.depth + 1,
        )
        self._item_repository.create(
            session_id=parent.session_id,
            agent_id=child.id,
            sequence=1,
            item_type=ItemType.MESSAGE,
            role=MessageRole.USER,
            content=task.strip(),
        )

        child_result = await self.run_agent(child.id, max_turn_count=self._subagent_max_turn_count)
        if child_result.status == "waiting":
            return {
                "status": "waiting",
                "waiting_for": WaitingFor(
                    call_id=function_call.call_id,
                    type="agent",
                    name=function_call.name,
                    description=f'Waiting for agent "{template.name}" to complete.',
                    agent_id=child.id,
                ),
                "is_error": False,
            }
        if child_result.status == "completed":
            return {
                "status": "completed",
                "output": self._extract_agent_result(child_result.agent),
                "is_error": False,
            }
        if child_result.status == "cancelled":
            return {
                "status": "failed",
                "output": f'Agent "{template.name}" was cancelled.',
                "is_error": True,
            }
        return {
            "status": "failed",
            "output": child_result.error or child_result.agent.error or f'Agent "{template.name}" failed.',
            "is_error": True,
        }

    async def _handle_send_message(
        self,
        sender: Agent,
        function_call: ProviderFunctionCall,
    ) -> dict[str, Any]:
        target_id = function_call.arguments.get("to")
        message = function_call.arguments.get("message")
        if not isinstance(target_id, str) or target_id.strip() == "":
            return tool_error(
                "send_message expects a non-empty string argument: 'to'.",
                hint="Podaj identyfikator docelowego agenta.",
                details={"received": {"to": target_id}},
            )
        if not isinstance(message, str) or message.strip() == "":
            return tool_error(
                "send_message expects a non-empty string argument: 'message'.",
                hint="Podaj treść wiadomości dla docelowego agenta.",
                details={"received": {"message": message}},
            )

        target = self._agent_repository.get_by_id(target_id.strip())
        if target is None:
            return tool_error(
                f"Target agent not found: {target_id}",
                hint="Upewnij się, że używasz istniejącego agent_id.",
                details={"to": target_id},
                retryable=False,
            )
        if target.session_id != sender.session_id:
            return tool_error(
                "Target agent belongs to another session.",
                hint="Wysyłaj wiadomości tylko do agentów z tej samej sesji.",
                details={"to": target.id, "session_id": target.session_id},
                retryable=False,
            )

        next_sequence = self._item_repository.get_last_sequence(target.id) + 1
        self._item_repository.create(
            session_id=target.session_id,
            agent_id=target.id,
            sequence=next_sequence,
            item_type=ItemType.MESSAGE,
            role=MessageRole.SYSTEM,
            content=message.strip(),
        )
        return tool_ok({"to": target.id, "delivered": True})

    async def _maybe_propagate_to_parent(self, run_result: RunResult) -> None:
        agent = run_result.agent
        if agent.parent_id is None or agent.source_call_id is None:
            return
        if run_result.status not in {"completed", "failed"}:
            return

        await self.deliver_result(
            agent_id=agent.parent_id,
            call_id=agent.source_call_id,
            output=(
                self._extract_agent_result(agent)
                if run_result.status == "completed"
                else run_result.error or agent.error or "Child agent failed."
            ),
            is_error=run_result.status == "failed",
        )

    def _record_function_result(
        self,
        *,
        session_id: str,
        agent_id: str,
        sequence: int,
        call_id: str,
        name: str,
        output: str,
        is_error: bool,
    ) -> int:
        item = self._item_repository.create(
            session_id=session_id,
            agent_id=agent_id,
            sequence=sequence + 1,
            item_type=ItemType.FUNCTION_CALL_OUTPUT,
            call_id=call_id,
            name=name,
            output=output,
            is_error=is_error,
        )
        self._observability.record_item(item)
        return sequence + 1

    def _map_items_to_provider_input(
        self,
        items: list[Item],
    ) -> list[ProviderMessageInput | ProviderFunctionCallInput | ProviderFunctionResultInput]:
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

            if item.type == ItemType.FUNCTION_CALL_OUTPUT and item.call_id and item.output is not None:
                mapped_items.append(
                    ProviderFunctionResultInput(
                        call_id=item.call_id,
                        name=item.name or "",
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

    def _get_agent(self, agent_id: str) -> Agent:
        agent = self._agent_repository.get_by_id(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} does not exist.")
        return agent

    def _get_session(self, session_id: str) -> Session:
        session = self._session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} does not exist.")
        return session

    def _extract_agent_result(self, agent: Agent) -> Any:
        if agent.result is not None:
            return agent.result

        items = self._item_repository.list_by_agent(agent.id)
        for item in reversed(items):
            if item.type == ItemType.MESSAGE and item.role == MessageRole.ASSISTANT and item.content is not None:
                return item.content
            if item.type == ItemType.FUNCTION_CALL_OUTPUT and item.output is not None:
                return self._deserialize_tool_output(item.output)
        return ""

    @staticmethod
    def _extract_completion_result(response: ProviderResponse) -> Any:
        text_parts = [item.text for item in response.output if isinstance(item, ProviderTextOutput)]
        return "".join(text_parts).strip()

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
    def _serialize_tool_result_output(tool_name: str, tool_result: dict[str, Any]) -> str:
        del tool_name
        if tool_result.get("ok"):
            output = tool_result.get("output")
            return AgentRunner._serialize_tool_output(output)

        return AgentRunner._serialize_tool_output(tool_result)

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
