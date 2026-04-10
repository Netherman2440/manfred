import logging
from contextlib import nullcontext
from unittest.mock import Mock, patch

from app.db.base import utcnow
from app.config import Settings
from app.domain import Agent, AgentConfig, AgentStatus
from app.events import (
    AgentCompletedEvent,
    AgentStartedEvent,
    GenerationCompletedEvent,
    ToolCompletedEvent,
    build_event_context,
)
from app.observability.langfuse_subscriber import LangfuseSubscriber, build_langfuse_subscriber
from app.providers import ProviderMessageInputItem, ProviderTextOutputItem, ProviderUsage


def make_agent() -> Agent:
    now = utcnow()
    return Agent(
        id="agent-1",
        session_id="session-1",
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


def test_langfuse_subscriber_is_disabled_without_credentials(caplog) -> None:  # noqa: ANN001
    caplog.set_level(logging.INFO, logger="app.observability.langfuse")

    subscriber = build_langfuse_subscriber(
        Settings(
            LANGFUSE_ENABLED=True,
            LANGFUSE_PUBLIC_KEY="",
            LANGFUSE_SECRET_KEY="",
        )
    )

    assert subscriber is None
    assert "credentials are missing" in caplog.text


def test_langfuse_subscriber_builds_client_when_sdk_is_available() -> None:
    with patch("langfuse.Langfuse") as langfuse_client:
        subscriber = build_langfuse_subscriber(
            Settings(
                LANGFUSE_ENABLED=True,
                LANGFUSE_PUBLIC_KEY="pk-test",
                LANGFUSE_SECRET_KEY="sk-test",
                LANGFUSE_HOST="https://cloud.langfuse.com",
                LANGFUSE_ENVIRONMENT="development",
            )
        )

    assert isinstance(subscriber, LangfuseSubscriber)
    langfuse_client.assert_called_once_with(
        public_key="pk-test",
        secret_key="sk-test",
        base_url="https://cloud.langfuse.com",
        environment="development",
    )


def test_langfuse_subscriber_ends_observations_without_time_argument() -> None:
    client = Mock()
    agent_observation = Mock()
    agent_observation.id = "obs-agent-1"
    generation_observation = Mock()
    tool_observation = Mock()
    client.start_observation.side_effect = [
        agent_observation,
        generation_observation,
        tool_observation,
    ]
    subscriber = LangfuseSubscriber(client=client)
    agent = make_agent()
    ctx = build_event_context(agent, "trace-1")

    subscriber._handle_agent_started(
        AgentStartedEvent(
            ctx=ctx,
            model=agent.config.model,
            task=agent.config.task,
            user_input="Hej",
        )
    )
    subscriber._handle_generation_completed(
        GenerationCompletedEvent(
            ctx=ctx,
            model="openai/gpt-4o-mini",
            instructions=agent.config.task,
            input=[],
            output=[ProviderTextOutputItem(text="Licze.")],
            usage=ProviderUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            duration_ms=100,
            start_time=utcnow(),
        )
    )
    subscriber._handle_tool_completed(
        ToolCompletedEvent(
            ctx=ctx,
            call_id="call-1",
            name="calculator",
            arguments={"a": 1, "b": 2},
            output={"ok": True, "output": "3"},
            duration_ms=5,
            start_time=utcnow(),
        )
    )
    subscriber._handle_agent_completed(
        AgentCompletedEvent(
            ctx=ctx,
            duration_ms=200,
            usage=ProviderUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            result="3",
        )
    )

    generation_observation.end.assert_called_once_with()
    tool_observation.end.assert_called_once_with()
    agent_observation.end.assert_called_once_with()


def test_langfuse_subscriber_sets_trace_io_and_simplifies_generation_payloads() -> None:
    client = Mock()
    agent_observation = Mock()
    agent_observation.id = "obs-agent-1"
    generation_observation = Mock()
    propagated_attributes: list[dict[str, str | None]] = []
    client.start_observation.side_effect = [
        agent_observation,
        generation_observation,
    ]
    subscriber = LangfuseSubscriber(
        client=client,
        propagate_attributes_fn=lambda **kwargs: _record_trace_attributes(propagated_attributes, **kwargs),
    )
    agent = make_agent()
    ctx = build_event_context(agent, "trace-1")

    subscriber._handle_agent_started(
        AgentStartedEvent(
            ctx=ctx,
            model=agent.config.model,
            task=agent.config.task,
            user_input="Hej, policz to.",
        )
    )
    subscriber._handle_generation_completed(
        GenerationCompletedEvent(
            ctx=ctx,
            model="openai/gpt-4o-mini",
            instructions=agent.config.task,
            input=[
                ProviderMessageInputItem(role="user", content="Stare pytanie."),
                ProviderMessageInputItem(role="user", content="Hej, policz to."),
                ProviderMessageInputItem(role="assistant", content="Zaraz policze."),
                ProviderMessageInputItem(role="user", content="A co wiesz o Polsce?"),
            ],
            output=[ProviderTextOutputItem(text="Wynik to 15538.")],
            usage=ProviderUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            duration_ms=100,
            start_time=utcnow(),
        )
    )
    subscriber._handle_agent_completed(
        AgentCompletedEvent(
            ctx=ctx,
            duration_ms=200,
            usage=ProviderUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            result="Wynik to 15538.",
        )
    )

    agent_observation.set_trace_io.assert_any_call(input="Hej, policz to.")
    agent_observation.set_trace_io.assert_any_call(output="Wynik to 15538.")
    generation_call = client.start_observation.call_args_list[1]
    assert generation_call.kwargs["input"] == "A co wiesz o Polsce?"
    assert generation_call.kwargs["output"] == "Wynik to 15538."
    assert propagated_attributes == [
        {
            "user_id": None,
            "session_id": "session-1",
            "trace_name": "manfred",
        },
        {
            "user_id": None,
            "session_id": "session-1",
            "trace_name": "manfred",
        },
    ]


def _record_trace_attributes(
    storage: list[dict[str, str | None]],
    **kwargs: str | None,
):
    storage.append(dict(kwargs))
    return nullcontext()
