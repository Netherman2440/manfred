from typing import Literal

from app.domain.tool import FunctionToolDefinition, Tool, tool_error, tool_ok


Operation = Literal["add", "subtract", "multiply", "divide"]


async def calculator_handler(args: dict[str, object], signal: object | None = None) -> dict[str, object]:
    del signal
    operation = args.get("operation")
    a = args.get("a")
    b = args.get("b")

    if operation not in {"add", "subtract", "multiply", "divide"}:
        return tool_error(
            f"Unknown operation: {operation}",
            hint="Użyj jednej z operacji: add, subtract, multiply, divide.",
            details={
                "received": {"operation": operation},
                "expected": {"operation": ["add", "subtract", "multiply", "divide"]},
            },
        )
    if isinstance(a, bool) or not isinstance(a, (int, float)) or isinstance(b, bool) or not isinstance(b, (int, float)):
        return tool_error(
            "Calculator expects numeric values for 'a' and 'b'.",
            hint="Podaj pola 'a' i 'b' jako liczby.",
            details={
                "received": {"a": a, "b": b},
                "expected": {"a": "number", "b": "number"},
            },
        )
    if operation == "divide" and b == 0:
        return tool_error(
            "Division by zero",
            hint="Dla operacji divide podaj 'b' różne od 0.",
            details={
                "received": {"a": a, "b": b, "operation": operation},
                "expected": {"b": "number != 0"},
            },
        )

    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    else:
        result = a / b

    return tool_ok(str(result))


calculator_tool = Tool(
    type="sync",
    definition=FunctionToolDefinition(
        name="calculator",
        description="Perform basic math operations: add, subtract, multiply, divide",
        parameters={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "subtract", "multiply", "divide"],
                    "description": "The math operation to perform",
                },
                "a": {
                    "type": "number",
                    "description": "First operand",
                },
                "b": {
                    "type": "number",
                    "description": "Second operand",
                },
            },
            "required": ["operation", "a", "b"],
        },
    ),
    handler=calculator_handler,
)
