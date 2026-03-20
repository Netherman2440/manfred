from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from app.config import Settings


def load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[1] / relative_path
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {module_path}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_task_module = load_module(
    "ai_devs_verify_task_tool",
    "app/agent/tools/ai_devs/verify_task.py",
)


class FakeHeaders:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get(self, key: str, default: str | None = None) -> str | None:
        if key.lower() == "content-type":
            return self._content_type
        return default


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200, content_type: str = "application/json; charset=utf-8") -> None:
        self._body = body
        self.status = status
        self.headers = FakeHeaders(content_type)

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class AIDevsToolsTest(unittest.IsolatedAsyncioTestCase):
    async def test_verify_task_posts_normalized_json_answer(self) -> None:
        tool = verify_task_module.build_verify_task_tool(
            Settings(AI_DEVS_API_KEY="test-key", AI_DEVS_HUB_URL="https://hub.ag3nts.org"),
        )

        def fake_urlopen(req, timeout):
            self.assertEqual(timeout, 30.0)
            payload = json.loads(req.data.decode("utf-8"))
            self.assertEqual(payload["apikey"], "test-key")
            self.assertEqual(payload["task"], "people")
            self.assertIsInstance(payload["answer"], list)
            self.assertEqual(payload["answer"][0]["name"], "Jan")
            return FakeResponse(b'{"code":0,"message":"{FLG:TEST}"}')

        with patch.object(verify_task_module.request, "urlopen", side_effect=fake_urlopen):
            result = await tool.handler(
                {
                    "task": "people",
                    "answer": json.dumps(
                        [
                            {
                                "name": "Jan",
                                "surname": "Kowalski",
                                "gender": "M",
                                "born": 1990,
                                "city": "Grudziadz",
                                "tags": ["transport"],
                            }
                        ]
                    ),
                }
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["output"]["status_code"], 200)
        self.assertEqual(result["output"]["submitted_answer_count"], 1)
        self.assertEqual(result["output"]["response"]["message"], "{FLG:TEST}")

    async def test_verify_task_validates_people_payload_shape(self) -> None:
        tool = verify_task_module.build_verify_task_tool(
            Settings(AI_DEVS_API_KEY="test-key", AI_DEVS_HUB_URL="https://hub.ag3nts.org"),
        )

        with self.assertRaisesRegex(ValueError, "field 'born'"):
            await tool.handler(
                {
                    "task": "people",
                    "answer": [
                        {
                            "name": "Jan",
                            "surname": "Kowalski",
                            "gender": "M",
                            "born": "1990",
                            "city": "Grudziadz",
                            "tags": ["transport"],
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
