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


tiktokenizer_module = load_module(
    "tiktokenizer_tool",
    "app/agent/tools/tiktokenizer.py",
)


class TiktokenizerToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_tiktokenizer_estimates_tokens(self) -> None:
        result = await tiktokenizer_module.tiktokenizer_tool.handler({"text": "12345"})

        self.assertEqual(result, {"ok": True, "output": {"token_count": 2}})

    async def test_tiktokenizer_returns_zero_for_empty_text(self) -> None:
        result = await tiktokenizer_module.tiktokenizer_tool.handler({"text": ""})

        self.assertEqual(result, {"ok": True, "output": {"token_count": 0}})

    async def test_tiktokenizer_rejects_invalid_text(self) -> None:
        result = await tiktokenizer_module.tiktokenizer_tool.handler({"text": 123})

        self.assertFalse(result["ok"])
        self.assertEqual(result["details"]["expected"]["text"], "string")


if __name__ == "__main__":
    unittest.main()
