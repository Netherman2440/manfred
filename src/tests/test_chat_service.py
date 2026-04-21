import json

from app.domain import Agent, AgentConfig, AgentStatus, Item, ItemType, WaitingForEntry
from app.services.chat_service import ChatService
from app.db.base import utcnow


def test_build_response_output_deserializes_tool_success_result() -> None:
    items = [
        Item(
            id="item-1",
            session_id="session-1",
            agent_id="agent-1",
            sequence=1,
            type=ItemType.FUNCTION_CALL_OUTPUT,
            role=None,
            content=None,
            call_id="call-1",
            name="calculator",
            arguments_json=None,
            output=json.dumps({"ok": True, "output": "15538.0"}),
            is_error=False,
            created_at=utcnow(),
        )
    ]

    output = ChatService._build_response_output(items, include_tool_result=True)

    assert len(output) == 1
    assert output[0].type == "function_call_output"
    assert output[0].output == "15538.0"
    assert output[0].is_error is False


def test_build_response_output_deserializes_tool_error_result() -> None:
    items = [
        Item(
            id="item-1",
            session_id="session-1",
            agent_id="agent-1",
            sequence=1,
            type=ItemType.FUNCTION_CALL_OUTPUT,
            role=None,
            content=None,
            call_id="call-1",
            name="calculator",
            arguments_json=None,
            output=json.dumps({"ok": False, "error": "calculator failed"}),
            is_error=True,
            created_at=utcnow(),
        )
    ]

    output = ChatService._build_response_output(items, include_tool_result=True)

    assert len(output) == 1
    assert output[0].type == "function_call_output"
    assert output[0].output == "calculator failed"
    assert output[0].is_error is True


def test_append_waiting_tool_results_exposes_waiting_question() -> None:
    now = utcnow()
    agent = Agent(
        id="agent-1",
        session_id="session-1",
        trace_id="trace-1",
        root_agent_id="agent-1",
        parent_id=None,
        source_call_id=None,
        depth=0,
        agent_name="manfred",
        status=AgentStatus.WAITING,
        turn_count=1,
        waiting_for=[
            WaitingForEntry(
                call_id="call-1",
                type="human",
                name="ask_user",
                description="Jakiego zamku szukasz?",
                agent_id="agent-1",
            )
        ],
        config=AgentConfig(
            model="openrouter:test-model",
            task="Test task",
            tools=[],
            temperature=None,
        ),
        created_at=now,
        updated_at=now,
    )

    output = ChatService._append_waiting_tool_results(agent, [], include_tool_result=True)

    assert len(output) == 1
    assert output[0].type == "function_call_output"
    assert output[0].call_id == "call-1"
    assert output[0].output == "Jakiego zamku szukasz?"
