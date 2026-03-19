from app.agent.tools.audio.generate_audio import build_generate_audio_tool
from app.agent.tools.audio.transcribe_audio import build_transcribe_audio_tool
from app.services.audio import AudioService


def build_audio_tools(audio_service: AudioService):
    return [
        build_transcribe_audio_tool(audio_service),
        build_generate_audio_tool(audio_service),
    ]


__all__ = [
    "build_audio_tools",
    "build_generate_audio_tool",
    "build_transcribe_audio_tool",
]
