import logging

from app.db.base import utcnow
from app.domain import Agent, AgentConfig, AgentStatus
from app.events import (
    AgentCompletedEvent,
    AgentStartedEvent,
    EventBus,
    GenerationCompletedEvent,
    ToolCalledEvent,
    ToolCompletedEvent,
    build_event_context,
)
from app.observability import subscribe_event_logger
from app.providers import ProviderFunctionCallOutputItem, ProviderTextOutputItem, ProviderUsage


def make_agent() -> Agent:
    now = utcnow()
    return Agent(
        id="agent-1",
        session_id="session-1",
        trace_id=None,
        root_agent_id="agent-1",
        parent_id=None,
        source_call_id=None,
        depth=0,
        agent_name="manfred",
        status=AgentStatus.PENDING,
        turn_count=0,
        waiting_for=[],
        config=AgentConfig(
            model="openrouter:test-model",
            task="Test task",
            tools=[],
            temperature=None,
        ),
        created_at=now,
        updated_at=now,
    )


def test_event_logger_logs_user_facing_fields_without_internal_ids(caplog) -> None:  # noqa: ANN001
    event_bus = EventBus()
    agent = make_agent()
    unsubscribe = subscribe_event_logger(event_bus)
    caplog.set_level(logging.INFO, logger="app.events")

    try:
        event_bus.emit(
            AgentStartedEvent(
                ctx=build_event_context(agent, "trace-1"),
                model=agent.config.model,
                task=agent.config.task,
                user_input="Hej, policz to.",
            )
        )
        event_bus.emit(
            GenerationCompletedEvent(
                ctx=build_event_context(agent, "trace-1"),
                model="openai/gpt-4o-mini",
                instructions="Test task",
                input=[],
                output=[
                    ProviderTextOutputItem(text="Licze dalej."),
                    ProviderFunctionCallOutputItem(
                        call_id="call-1",
                        name="calculator",
                        arguments={"operation": "multiply", "a": 123, "b": 142},
                    ),
                ],
                usage=ProviderUsage(
                    input_tokens=275,
                    output_tokens=22,
                    total_tokens=297,
                    cached_tokens=128,
                ),
                duration_ms=1200,
                start_time=utcnow(),
            )
        )
    finally:
        unsubscribe()

    assert 'event=agent.started agent=manfred content="Hej, policz to."' in caplog.text
    assert "input_tokens=" not in caplog.text.splitlines()[0]
    assert "event=generation.completed agent=manfred" in caplog.text
    assert 'content="Licze dalej."' in caplog.text
    assert 'tool_calls=["calculator"]' in caplog.text
    assert "input_tokens=275 output_tokens=22 total_tokens=297 cached_tokens=128" in caplog.text
    assert "trace_id=" not in caplog.text
    assert "agent_id=" not in caplog.text


def test_event_logger_logs_tool_results_and_agent_result(caplog) -> None:  # noqa: ANN001
    event_bus = EventBus()
    agent = make_agent()
    unsubscribe = subscribe_event_logger(event_bus)
    caplog.set_level(logging.INFO, logger="app.events")

    try:
        event_bus.emit(
            ToolCalledEvent(
                ctx=build_event_context(agent, "trace-1"),
                call_id="call-1",
                name="calculator",
                arguments={"operation": "subtract", "a": 17466, "b": 1928},
            )
        )
        event_bus.emit(
            ToolCompletedEvent(
                ctx=build_event_context(agent, "trace-1"),
                call_id="call-1",
                name="calculator",
                arguments={"operation": "subtract", "a": 17466, "b": 1928},
                output={"ok": True, "output": "15538.0"},
                duration_ms=4,
                start_time=utcnow(),
            )
        )
        event_bus.emit(
            AgentCompletedEvent(
                ctx=build_event_context(agent, "trace-1"),
                duration_ms=3071,
                usage=ProviderUsage(input_tokens=956, output_tokens=71, total_tokens=1027),
                result="Wynik to 15538.",
            )
        )
    finally:
        unsubscribe()

    assert "event=tool.called agent=manfred" in caplog.text
    assert "input_tokens=" not in caplog.text.splitlines()[0]
    assert 'tool=calculator tool_arguments={"operation": "subtract", "a": 17466, "b": 1928}' in caplog.text
    assert "event=tool.completed agent=manfred content=15538.0" in caplog.text
    assert "input_tokens=" not in caplog.text.splitlines()[1]
    assert 'tool_result={"ok": true, "output": "15538.0"}' in caplog.text
    assert 'event=agent.completed agent=manfred content="Wynik to 15538."' in caplog.text
    assert "input_tokens=956 output_tokens=71 total_tokens=1027 cached_tokens=0" in caplog.text
