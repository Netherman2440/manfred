from typing import Literal

from app.domain.tool import FunctionToolDefinition, Tool


Operation = Literal["add", "subtract", "multiply", "divide"]


async def calculator_handler(args: dict[str, object], signal: object | None = None) -> dict[str, bool | str]:
    operation = args.get("operation")
    a = args.get("a")
    b = args.get("b")

    if operation not in {"add", "subtract", "multiply", "divide"}:
        raise ValueError(f"Unknown operation: {operation}")
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Calculator expects numeric values for 'a' and 'b'.")
    if operation == "divide" and b == 0:
        raise ValueError("Division by zero")

    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    else:
        result = a / b

    return {"ok": True, "output": str(result)}


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
