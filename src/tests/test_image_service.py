import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.services.images import OpenAIImageService


class StubResponsesClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="A small red square on a white background.")


class StubImagesClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(b64_json=base64.b64encode(b"png-bytes").decode("utf-8"))]
        )


class StubOpenAIClient:
    def __init__(self) -> None:
        self.responses = StubResponsesClient()
        self.images = StubImagesClient()


class OpenAIImageServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_image_uses_custom_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_root = Path(tmp_dir)
            input_dir = workspace_root / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "sample.png").write_bytes(b"fake image")

            client = StubOpenAIClient()
            service = OpenAIImageService(
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                workspace_root=workspace_root,
                client=client,
            )

            analysis = await service.analyze_image(
                "input/sample.png",
                "Classify whether this image contains a vehicle. Answer yes or no.",
            )

        self.assertEqual(analysis, "A small red square on a white background.")
        self.assertEqual(
            client.responses.calls[0]["input"][0]["content"][0]["text"],
            "Classify whether this image contains a vehicle. Answer yes or no.",
        )

    async def test_describe_image_returns_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_root = Path(tmp_dir)
            input_dir = workspace_root / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "sample.png").write_bytes(b"fake image")

            client = StubOpenAIClient()
            service = OpenAIImageService(
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                workspace_root=workspace_root,
                client=client,
            )

            description = await service.describe_image("input/sample.png")

        self.assertEqual(description, "A small red square on a white background.")
        self.assertEqual(len(client.responses.calls), 1)
        self.assertEqual(client.responses.calls[0]["model"], "gpt-4.1-mini")

    async def test_create_image_writes_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_root = Path(tmp_dir)
            client = StubOpenAIClient()
            service = OpenAIImageService(
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                workspace_root=workspace_root,
                client=client,
            )

            output_path = await service.create_image("Red Square")
            generated_file = workspace_root / output_path
            self.assertTrue(generated_file.exists())
            self.assertEqual(generated_file.read_bytes(), b"png-bytes")

        self.assertEqual(len(client.images.calls), 1)
        self.assertEqual(client.images.calls[0]["model"], "gpt-image-1.5")
        self.assertNotIn("response_format", client.images.calls[0])
        self.assertTrue(output_path.startswith("output/"))
        self.assertTrue(output_path.endswith(".png"))

    async def test_create_image_requests_base64_for_dalle_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_root = Path(tmp_dir)
            client = StubOpenAIClient()
            service = OpenAIImageService(
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                workspace_root=workspace_root,
                image_model="dall-e-3",
                client=client,
            )

            await service.create_image("Red Square")

        self.assertEqual(client.images.calls[0]["response_format"], "b64_json")


if __name__ == "__main__":
    unittest.main()
