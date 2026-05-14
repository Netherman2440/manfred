from __future__ import annotations

from typing import Any, Literal

from app.domain.tool import FunctionToolDefinition, Tool, ToolExecutionContext

Operation = Literal["add", "subtract", "multiply", "divide"]
SUPPORTED_OPERATIONS: tuple[Operation, ...] = ("add", "subtract", "multiply", "divide")


def _to_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"'{name}' must be a number")
    return float(value)


def calculate(*, operation: Operation, a: float, b: float) -> float:
    if operation == "add":
        return a + b
    if operation == "subtract":
        return a - b
    if operation == "multiply":
        return a * b
    if operation == "divide":
        if b == 0:
            raise ValueError("Division by zero")
        return a / b
    raise ValueError(f"Unknown operation: {operation}")


async def handle_calculator(args: dict[str, Any], context: ToolExecutionContext) -> dict[str, bool | str]:
    del context
    operation = args.get("operation")
    if operation not in SUPPORTED_OPERATIONS:
        raise ValueError(f"'operation' must be one of: {', '.join(SUPPORTED_OPERATIONS)}")

    a = _to_number(args.get("a"), "a")
    b = _to_number(args.get("b"), "b")
    result = calculate(operation=operation, a=a, b=b)
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
                    "enum": list(SUPPORTED_OPERATIONS),
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
    handler=handle_calculator,
)
