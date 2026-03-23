from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest


def load_tool_builder(module_name: str, relative_path: str, attribute_name: str):
    module_path = Path(__file__).resolve().parents[1] / relative_path
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {module_path}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, attribute_name)


build_create_image_tool = load_tool_builder(
    "image_create_tool",
    "app/agent/tools/images/create_image.py",
    "build_create_image_tool",
)
build_describe_image_tool = load_tool_builder(
    "image_describe_tool",
    "app/agent/tools/images/describe_image.py",
    "build_describe_image_tool",
)


class StubImageService:
    async def create_image(self, prompt: str) -> str:
        return f"output/{prompt.lower().replace(' ', '_')}.png"

    async def describe_image(self, path: str) -> str:
        return f"description:{path}"


class ImageToolsTest(unittest.IsolatedAsyncioTestCase):
    async def test_describe_image_tool_returns_plain_description(self) -> None:
        tool = build_describe_image_tool(StubImageService())

        result = await tool.handler({"path": "input/demo.png"})

        self.assertEqual(result, {"ok": True, "output": "description:input/demo.png"})

    async def test_create_image_tool_returns_output_path(self) -> None:
        tool = build_create_image_tool(StubImageService())

        result = await tool.handler({"prompt": "Blue Robot"})

        self.assertEqual(result, {"ok": True, "output": {"path": "output/blue_robot.png"}})

    async def test_describe_image_tool_returns_soft_error_for_missing_path_argument(self) -> None:
        tool = build_describe_image_tool(StubImageService())

        result = await tool.handler({"path": ""})

        self.assertFalse(result["ok"])
        self.assertEqual(result["details"]["expected"]["path"], "non-empty string")


if __name__ == "__main__":
    unittest.main()
