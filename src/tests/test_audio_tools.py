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


build_generate_audio_tool = load_tool_builder(
    "audio_generate_tool",
    "app/agent/tools/audio/generate_audio.py",
    "build_generate_audio_tool",
)
build_transcribe_audio_tool = load_tool_builder(
    "audio_transcribe_tool",
    "app/agent/tools/audio/transcribe_audio.py",
    "build_transcribe_audio_tool",
)


class StubAudioService:
    async def transcribe_audio(self, path: str) -> str:
        return f"transcribed:{path}"

    async def generate_audio(self, text: str) -> str:
        return f"output/{text.lower().replace(' ', '_')}.mp3"


class AudioToolsTest(unittest.IsolatedAsyncioTestCase):
    async def test_transcribe_audio_tool_returns_plain_transcription(self) -> None:
        tool = build_transcribe_audio_tool(StubAudioService())

        result = await tool.handler({"path": "input/demo.wav"})

        self.assertEqual(result, {"ok": True, "output": "transcribed:input/demo.wav"})

    async def test_generate_audio_tool_returns_output_path(self) -> None:
        tool = build_generate_audio_tool(StubAudioService())

        result = await tool.handler({"text": "Hello World"})

        self.assertEqual(result, {"ok": True, "output": {"path": "output/hello_world.mp3"}})


if __name__ == "__main__":
    unittest.main()
