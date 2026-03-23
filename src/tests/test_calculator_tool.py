from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest


def load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[1] / relative_path
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {module_path}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


calculator_module = load_module(
    "calculator_tool",
    "app/agent/tools/calculator.py",
)


class CalculatorToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_calculator_returns_result_for_valid_operation(self) -> None:
        result = await calculator_module.calculator_tool.handler(
            {"operation": "multiply", "a": 6, "b": 7}
        )

        self.assertEqual(result, {"ok": True, "output": "42"})

    async def test_calculator_returns_soft_error_for_invalid_operation(self) -> None:
        result = await calculator_module.calculator_tool.handler(
            {"operation": "pow", "a": 2, "b": 3}
        )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["details"]["expected"]["operation"],
            ["add", "subtract", "multiply", "divide"],
        )


if __name__ == "__main__":
    unittest.main()
