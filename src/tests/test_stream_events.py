"""Tests for runtime events bridged onto the chat SSE stream (Part A)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain import FunctionToolDefinition, ToolExecutionContext, WaitingForEntry
from app.providers import (
    ProviderFunctionCallDoneEvent,
    ProviderFunctionCallOutputItem,
    ProviderResponse,
    ProviderTextDoneEvent,
    ProviderTextOutputItem,
    ProviderUsage,
)
from app.providers.types import ProviderDoneEvent, ProviderTextDeltaEvent
from app.runtime.stream_events import (
    AgentCancelledStreamEvent,
    AgentCompletedStreamEvent,
    AgentFailedStreamEvent,
    AgentWaitingStreamEvent,
    ToolCompletedStreamEvent,
    ToolFailedStreamEvent,
    serialize_runtime_stream_event,
)
from app.tools.definitions.ask_user import ask_user_tool
from app.tools.registry import Tool
from tests.test_runner_events import db_session, make_runner

__all__ = ["db_session", "make_runner"]


@pytest.mark.asyncio
async def test_stream_emits_agent_waiting_with_entry_for_ask_user(db_session: Session) -> None:
    runner, agent_id, _ = make_runner(
        db_session,
        provider_responses=[],
        provider_streams=[
            [
                ProviderFunctionCallDoneEvent(
                    call_id="call-1",
                    name="ask_user",
                    arguments={"question": "Jaki format?"},
                ),
                ProviderDoneEvent(
                    response=ProviderResponse(
                        output=[
                            ProviderFunctionCallOutputItem(
                                call_id="call-1",
                                name="ask_user",
                                arguments={"question": "Jaki format?"},
                            )
                        ],
                        usage=ProviderUsage(input_tokens=8, output_tokens=3, total_tokens=11),
                        finish_reason="tool_calls",
                    )
                ),
            ]
        ],
        tools=[ask_user_tool],
    )

    events = [event async for event in runner.run_agent_stream(agent_id, last_agent_sequence=0)]

    assert [event.type for event in events] == [
        "function_call_done",
        "done",
        "agent.waiting",
    ]
    waiting_event = events[-1]
    assert isinstance(waiting_event, AgentWaitingStreamEvent)
    assert len(waiting_event.waiting_for) == 1
    entry = waiting_event.waiting_for[0]
    assert entry.type == "human"
    assert entry.call_id == "call-1"
    assert entry.description == "Jaki format?"


@pytest.mark.asyncio
async def test_stream_emits_tool_failed_for_failing_tool(db_session: Session) -> None:
    async def boom(
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> dict[str, object]:
        del arguments, context
        return {"ok": False, "error": "boom"}

    runner, agent_id, _ = make_runner(
        db_session,
        provider_responses=[],
        provider_streams=[
            [
                ProviderFunctionCallDoneEvent(call_id="call-1", name="boom", arguments={}),
                ProviderDoneEvent(
                    response=ProviderResponse(
                        output=[
                            ProviderFunctionCallOutputItem(call_id="call-1", name="boom", arguments={})
                        ],
                        usage=ProviderUsage(input_tokens=8, output_tokens=3, total_tokens=11),
                        finish_reason="tool_calls",
                    )
                ),
            ],
            [
                ProviderTextDeltaEvent(delta="Recovered"),
                ProviderTextDoneEvent(text="Recovered"),
                ProviderDoneEvent(
                    response=ProviderResponse(
                        output=[ProviderTextOutputItem(text="Recovered")],
                        usage=ProviderUsage(input_tokens=6, output_tokens=4, total_tokens=10),
                    )
                ),
            ],
        ],
        tools=[
            Tool(
                type="sync",
                definition=FunctionToolDefinition(
                    name="boom",
                    description="Always fails",
                    parameters={"type": "object"},
                ),
                handler=boom,
            )
        ],
    )

    events = [event async for event in runner.run_agent_stream(agent_id, last_agent_sequence=0)]

    types = [event.type for event in events]
    assert "tool.failed" in types
    assert types[-1] == "agent.completed"
    failed = next(event for event in events if event.type == "tool.failed")
    assert isinstance(failed, ToolFailedStreamEvent)
    assert failed.call_id == "call-1"
    assert failed.name == "boom"
    assert failed.error == "boom"


def test_serialize_runtime_stream_events() -> None:
    assert serialize_runtime_stream_event(
        ToolCompletedStreamEvent(call_id="c1", name="calculator", output={"ok": True, "output": "4"})
    ) == {
        "type": "tool.completed",
        "call_id": "c1",
        "name": "calculator",
        "output": {"ok": True, "output": "4"},
    }

    assert serialize_runtime_stream_event(
        ToolFailedStreamEvent(call_id="c1", name="boom", error="boom")
    ) == {"type": "tool.failed", "call_id": "c1", "name": "boom", "error": "boom"}

    assert serialize_runtime_stream_event(
        AgentWaitingStreamEvent(
            waiting_for=[
                WaitingForEntry(call_id="c1", type="human", name="ask_user", description="Q?")
            ]
        )
    ) == {
        "type": "agent.waiting",
        "waiting_for": [
            {
                "call_id": "c1",
                "type": "human",
                "name": "ask_user",
                "description": "Q?",
                "agent_id": None,
            }
        ],
    }

    assert serialize_runtime_stream_event(AgentCompletedStreamEvent(agent_id="a1")) == {
        "type": "agent.completed",
        "agent_id": "a1",
    }
    assert serialize_runtime_stream_event(AgentFailedStreamEvent(agent_id="a1", error="x")) == {
        "type": "agent.failed",
        "agent_id": "a1",
        "error": "x",
    }
    assert serialize_runtime_stream_event(AgentCancelledStreamEvent(agent_id="a1")) == {
        "type": "agent.cancelled",
        "agent_id": "a1",
    }
