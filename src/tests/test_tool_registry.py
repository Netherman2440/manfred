import pytest

from app.domain import FunctionToolDefinition, Tool, ToolExecutionContext
from app.runtime.cancellation import CancellationSignal
from app.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_execute_replaces_context_tool_name() -> None:
    captured_context: ToolExecutionContext | None = None

    async def handler(
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> dict[str, bool | str]:
        nonlocal captured_context
        del arguments
        captured_context = context
        return {"ok": True, "output": "ok"}

    registry = ToolRegistry(
        tools=[
            Tool(
                type="sync",
                definition=FunctionToolDefinition(
                    name="canonical-name",
                    description="test",
                    parameters={"type": "object"},
                ),
                handler=handler,
            )
        ]
    )

    result = await registry.execute(
        "canonical-name",
        {},
        context=ToolExecutionContext(
            user_id="user-1",
            session_id="session-1",
            agent_id="agent-1",
            call_id="call-1",
            tool_name="stale-name",
        ),
    )

    assert result["ok"] is True
    assert captured_context is not None
    assert captured_context.tool_name == "canonical-name"


@pytest.mark.asyncio
async def test_execute_injects_signal_into_existing_context() -> None:
    captured_context: ToolExecutionContext | None = None
    signal = CancellationSignal()

    async def handler(
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> dict[str, bool | str]:
        nonlocal captured_context
        del arguments
        captured_context = context
        return {"ok": True, "output": "ok"}

    registry = ToolRegistry(
        tools=[
            Tool(
                type="sync",
                definition=FunctionToolDefinition(
                    name="capture",
                    description="test",
                    parameters={"type": "object"},
                ),
                handler=handler,
            )
        ]
    )

    result = await registry.execute(
        "capture",
        {},
        context=ToolExecutionContext(
            user_id="user-1",
            session_id="session-1",
            agent_id="agent-1",
            call_id="call-1",
            tool_name="capture",
        ),
        signal=signal,
    )

    assert result["ok"] is True
    assert captured_context is not None
    assert captured_context.signal is signal
