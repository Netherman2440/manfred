import tempfile
import unittest
from pathlib import Path

from app.services.audio import ElevenLabsAudioService


class StubElevenLabsAudioService(ElevenLabsAudioService):
    def __init__(self, *, workspace_root: Path) -> None:
        super().__init__(
            base_url="https://api.elevenlabs.io",
            api_key="test-key",
            workspace_root=workspace_root,
        )
        self.calls: list[tuple[str, str, dict[str, str] | None]] = []

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
        form_fields: dict[str, str] | None = None,
        files: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        del json_body, files
        self.calls.append((method, path, query))
        if path == "/v1/speech-to-text":
            return {"text": "Przykladowa transkrypcja"}
        if path == "/v1/voices":
            return {"voices": [{"voice_id": "voice-123"}]}
        raise AssertionError(f"Unexpected JSON request: {method} {path}")

    async def _request_binary(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> bytes:
        del json_body
        self.calls.append((method, path, query))
        if path != "/v1/text-to-speech/voice-123":
            raise AssertionError(f"Unexpected binary request: {method} {path}")
        return b"audio-bytes"


class ElevenLabsAudioServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_transcribe_audio_returns_transcribed_text(self) -> None:
        calls: list[tuple[str, str, dict[str, str] | None]]

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_root = Path(tmp_dir)
            input_dir = workspace_root / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "sample.wav").write_bytes(b"fake audio")

            service = StubElevenLabsAudioService(workspace_root=workspace_root)

            transcription = await service.transcribe_audio("input/sample.wav")
            calls = service.calls

        self.assertEqual(transcription, "Przykladowa transkrypcja")
        self.assertEqual(calls, [("POST", "/v1/speech-to-text", None)])

    async def test_generate_audio_fetches_voice_and_writes_output_file(self) -> None:
        calls: list[tuple[str, str, dict[str, str] | None]]

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_root = Path(tmp_dir)
            service = StubElevenLabsAudioService(workspace_root=workspace_root)

            output_path = await service.generate_audio("Hello from Manfred")
            calls = service.calls

            generated_file = workspace_root / output_path
            self.assertTrue(generated_file.exists())
            self.assertEqual(generated_file.read_bytes(), b"audio-bytes")

        self.assertEqual(
            calls,
            [
                ("GET", "/v1/voices", {"page_size": "1"}),
                ("POST", "/v1/text-to-speech/voice-123", {"output_format": "mp3_44100_128"}),
            ],
        )
        self.assertTrue(output_path.startswith("output/"))
        self.assertTrue(output_path.endswith(".mp3"))


if __name__ == "__main__":
    unittest.main()
