from app.db.base import utcnow
from app.domain import Agent, AgentConfig, AgentStatus
from app.events import AgentFailedEvent, AgentStartedEvent, EventBus, build_event_context


def make_agent() -> Agent:
    now = utcnow()
    return Agent(
        id="agent-1",
        session_id="session-1",
        root_agent_id="agent-1",
        parent_id=None,
        depth=0,
        agent_name="manfred",
        status=AgentStatus.PENDING,
        turn_count=0,
        config=AgentConfig(
            model="openrouter:test-model",
            task="Test task",
            tools=[],
            temperature=None,
        ),
        created_at=now,
        updated_at=now,
    )


def test_emit_calls_specific_and_any_subscribers() -> None:
    event_bus = EventBus()
    agent = make_agent()
    received: list[str] = []

    event_bus.subscribe("agent.started", lambda event: received.append(event.type))
    event_bus.subscribe("any", lambda event: received.append(f"any:{event.type}"))

    event_bus.emit(
        AgentStartedEvent(
            ctx=build_event_context(agent, "trace-1"),
            model=agent.config.model,
            task=agent.config.task,
        )
    )

    assert received == ["agent.started", "any:agent.started"]


def test_listener_exception_does_not_break_emit() -> None:
    event_bus = EventBus()
    agent = make_agent()
    received: list[str] = []

    def explode(_: object) -> None:
        raise RuntimeError("boom")

    event_bus.subscribe("agent.failed", explode)
    event_bus.subscribe("agent.failed", lambda event: received.append(event.type))

    event_bus.emit(
        AgentFailedEvent(
            ctx=build_event_context(agent, "trace-1"),
            error="Failure",
        )
    )

    assert received == ["agent.failed"]
