from __future__ import annotations

from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, tool_error, tool_ok
from app.services.audio import AudioService


GENERATE_AUDIO_DEFINITION = FunctionToolDefinition(
    name="generate_audio",
    description="Generate speech from text using ElevenLabs and save the result in workspace/output.",
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to synthesize into speech.",
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    },
)


def build_generate_audio_tool(audio_service: AudioService) -> Tool:
    async def generate_audio_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
        del signal
        text = args.get("text")
        if not isinstance(text, str) or text.strip() == "":
            return tool_error(
                "generate_audio expects a non-empty string argument: 'text'.",
                hint="Podaj pole 'text' jako niepusty tekst do syntezy mowy.",
                details={
                    "received": {"text": text},
                    "expected": {"text": "non-empty string"},
                },
            )

        output_path = await audio_service.generate_audio(text)
        return tool_ok({"path": output_path})

    return Tool(
        type="sync",
        definition=GENERATE_AUDIO_DEFINITION,
        handler=generate_audio_handler,
    )
