import json
import unittest
from datetime import UTC, datetime

from app.domain import (
    Agent,
    AgentConfig,
    AgentStatus,
    Item,
    ItemType,
    MessageRole,
    ProviderResponse,
    ProviderTextOutput,
    Session,
    SessionStatus,
    ToolRegistry,
)
from app.runtime.runner import AgentRunner
from app.services.observability import ObservabilityService


class StubProvider:
    def __init__(self, response: ProviderResponse) -> None:
        self._response = response

    def generate(self, provider_input: object) -> ProviderResponse:
        del provider_input
        return self._response


class StubAgentRepository:
    def __init__(self) -> None:
        self.updated_agents: list[Agent] = []

    def update(self, agent: Agent) -> Agent:
        self.updated_agents.append(agent)
        return agent


class StubSessionRepository:
    pass


class StubItemRepository:
    def __init__(self) -> None:
        self.created_items: list[Item] = []

    def list_by_agent(self, agent_id: str) -> list[Item]:
        del agent_id
        return []

    def get_last_sequence(self, agent_id: str) -> int:
        del agent_id
        return len(self.created_items)

    def create(
        self,
        *,
        session_id: str,
        agent_id: str,
        sequence: int,
        item_type: ItemType,
        role: MessageRole | None = None,
        content: str | None = None,
        call_id: str | None = None,
        name: str | None = None,
        arguments_json: str | None = None,
        output: str | None = None,
        is_error: bool = False,
    ) -> Item:
        item = Item(
            id=f"item-{len(self.created_items) + 1}",
            session_id=session_id,
            agent_id=agent_id,
            sequence=sequence,
            type=item_type,
            role=role,
            content=content,
            call_id=call_id,
            name=name,
            arguments_json=arguments_json,
            output=output,
            is_error=is_error,
            created_at=datetime.now(UTC),
        )
        self.created_items.append(item)
        return item


class StubAgentTemplateLoader:
    pass


class AgentRunnerToolSerializationTest(unittest.TestCase):
    def test_tool_error_keeps_full_payload_for_model(self) -> None:
        serialized = AgentRunner._serialize_tool_result_output(
            "verify_task",
            {
                "ok": False,
                "error": "AI Devs verify endpoint returned HTTP 429.",
                "hint": "Check details.response before retrying.",
                "details": {
                    "status_code": 429,
                    "response": {
                        "code": -985,
                        "message": "API rate limit exceeded. Please retry later.",
                        "retry_after": 29,
                    },
                },
                "retryable": True,
            },
        )

        parsed = json.loads(serialized)
        self.assertFalse(parsed["ok"])
        self.assertEqual(parsed["error"], "AI Devs verify endpoint returned HTTP 429.")
        self.assertEqual(parsed["hint"], "Check details.response before retrying.")
        self.assertEqual(parsed["details"]["status_code"], 429)
        self.assertEqual(parsed["details"]["response"]["retry_after"], 29)
        self.assertTrue(parsed["retryable"])

    def test_other_tool_error_also_stays_structured(self) -> None:
        serialized = AgentRunner._serialize_tool_result_output(
            "wait",
            {
                "ok": False,
                "error": "wait expects a numeric argument: 'time'.",
                "hint": "Pass time as a number >= 0.",
                "details": {"received": {"time": "soon"}},
                "retryable": True,
            },
        )

        parsed = json.loads(serialized)
        self.assertFalse(parsed["ok"])
        self.assertEqual(parsed["error"], "wait expects a numeric argument: 'time'.")
        self.assertEqual(parsed["details"]["received"]["time"], "soon")


class AgentRunnerLoggingTest(unittest.IsolatedAsyncioTestCase):
    async def test_execute_turn_logs_actual_response_model(self) -> None:
        item_repository = StubItemRepository()
        agent_repository = StubAgentRepository()
        runner = AgentRunner(
            agent_repository=agent_repository,
            session_repository=StubSessionRepository(),
            item_repository=item_repository,
            tool_registry=ToolRegistry(max_log_value_length=100),
            provider=StubProvider(
                ProviderResponse(
                    model="gpt-4.1-2026-03-01",
                    output=[ProviderTextOutput(text="Done")],
                )
            ),
            observability=ObservabilityService(),
            max_turn_count=5,
            subagent_max_turn_count=5,
            max_agent_depth=2,
            agent_template_loader=StubAgentTemplateLoader(),
        )
        timestamp = datetime.now(UTC)
        agent = Agent(
            id="agent-123",
            session_id="session-123",
            root_agent_id="agent-123",
            parent_id=None,
            source_call_id=None,
            depth=0,
            status=AgentStatus.RUNNING,
            waiting_for=(),
            result=None,
            error=None,
            turn_count=0,
            config=AgentConfig(model="gpt-requested", task="Be helpful."),
            created_at=timestamp,
            updated_at=timestamp,
        )
        session = Session(
            id="session-123",
            user_id="user-123",
            root_agent_id=agent.id,
            status=SessionStatus.ACTIVE,
            summary=None,
            created_at=timestamp,
            updated_at=timestamp,
        )

        with self.assertLogs("app.runtime.runner", level="INFO") as captured:
            turn_result = await runner.execute_turn(agent, session)

        self.assertEqual(turn_result.outcome, "completed")
        self.assertEqual(turn_result.agent.status, AgentStatus.COMPLETED)
        self.assertEqual(turn_result.agent.turn_count, 1)
        joined_output = "\n".join(captured.output)
        self.assertIn("LLM response: agent_id=agent-123 requested_model=gpt-requested", joined_output)
        self.assertIn("response_model=gpt-4.1-2026-03-01", joined_output)


if __name__ == "__main__":
    unittest.main()
