from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch


def load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[1] / relative_path
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {module_path}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wait_module = load_module(
    "wait_tool",
    "app/agent/tools/wait.py",
)


class WaitToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_wait_tool_sleeps_and_returns_next_action(self) -> None:
        with patch.object(wait_module.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
            result = await wait_module.wait_tool.handler(
                {"time": 3, "next_task": "Check inbox"},
            )

        sleep_mock.assert_awaited_once_with(3)
        self.assertEqual(
            result,
            {
                "ok": True,
                "output": "Wiat time's up Your next action should be: Check inbox",
            },
        )

    async def test_wait_tool_rejects_empty_next_task(self) -> None:
        with self.assertRaisesRegex(ValueError, "next_task"):
            await wait_module.wait_tool.handler({"time": 1, "next_task": "  "})


if __name__ == "__main__":
    unittest.main()
