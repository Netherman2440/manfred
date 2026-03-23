import unittest

from app.domain.tool import FunctionToolDefinition, Tool, ToolRegistry


async def successful_handler(args: dict[str, object], signal: object | None = None) -> dict[str, object]:
    return {"ok": True, "output": {"echo": args}}


async def failing_handler(args: dict[str, object], signal: object | None = None) -> dict[str, object]:
    raise RuntimeError("boom")


class ToolRegistryLoggingTest(unittest.IsolatedAsyncioTestCase):
    async def test_execute_logs_request_and_response(self) -> None:
        registry = ToolRegistry(max_log_value_length=500)
        registry.register(
            Tool(
                type="sync",
                definition=FunctionToolDefinition(
                    name="echo_tool",
                    description="Echo input",
                    parameters={"type": "object"},
                ),
                handler=successful_handler,
            )
        )

        with self.assertLogs("app.domain.tool", level="INFO") as captured:
            result = await registry.execute("echo_tool", {"prompt": "hello"}, call_id="call-123")

        self.assertEqual(result, {"ok": True, "output": {"echo": {"prompt": "hello"}}})
        joined_output = "\n".join(captured.output)
        self.assertIn("Tool request: name=echo_tool call_id=call-123", joined_output)
        self.assertIn('"prompt": "hello"', joined_output)
        self.assertIn("Tool response: name=echo_tool call_id=call-123", joined_output)
        self.assertIn('"ok": true', joined_output)

    async def test_execute_logs_exception_and_returns_error(self) -> None:
        registry = ToolRegistry(max_log_value_length=500)
        registry.register(
            Tool(
                type="sync",
                definition=FunctionToolDefinition(
                    name="failing_tool",
                    description="Raise error",
                    parameters={"type": "object"},
                ),
                handler=failing_handler,
            )
        )

        with self.assertLogs("app.domain.tool", level="ERROR") as captured:
            result = await registry.execute("failing_tool", {"prompt": "hello"}, call_id="call-456")

        self.assertEqual(
            result,
            {
                "ok": False,
                "error": "Tool execution failed.",
                "hint": "Spróbuj innego podejścia albo poinformuj użytkownika o problemie systemowym.",
                "details": {"tool": "failing_tool"},
                "retryable": False,
            },
        )
        joined_output = "\n".join(captured.output)
        self.assertIn("Tool execution failed: name=failing_tool call_id=call-456", joined_output)

    async def test_execute_truncates_large_payloads_in_logs(self) -> None:
        registry = ToolRegistry(max_log_value_length=40)
        registry.register(
            Tool(
                type="sync",
                definition=FunctionToolDefinition(
                    name="echo_tool",
                    description="Echo input",
                    parameters={"type": "object"},
                ),
                handler=successful_handler,
            )
        )

        with self.assertLogs("app.domain.tool", level="INFO") as captured:
            await registry.execute("echo_tool", {"payload": "x" * 200}, call_id="call-789")

        joined_output = "\n".join(captured.output)
        self.assertIn("[truncated ", joined_output)


if __name__ == "__main__":
    unittest.main()
