from __future__ import annotations

from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool
from app.services.audio import AudioService


TRANSCRIBE_AUDIO_DEFINITION = FunctionToolDefinition(
    name="transcribe_audio",
    description="Transcribe an audio file from the workspace into plain text using ElevenLabs.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to an audio file within the workspace.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
)


def build_transcribe_audio_tool(audio_service: AudioService) -> Tool:
    async def transcribe_audio_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
        del signal
        path = args.get("path")
        if not isinstance(path, str) or path.strip() == "":
            raise ValueError("transcribe_audio expects a non-empty string argument: 'path'.")

        transcription = await audio_service.transcribe_audio(path)
        return {"ok": True, "output": transcription}

    return Tool(
        type="sync",
        definition=TRANSCRIBE_AUDIO_DEFINITION,
        handler=transcribe_audio_handler,
    )
