from __future__ import annotations

from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool, tool_error, tool_ok
from app.services.images import ImageService


ANALYZE_IMAGE_DEFINITION = FunctionToolDefinition(
    name="analyze_image",
    description=(
        "Analyze an image file from the workspace according to a specific instruction or classification prompt. "
        "Use describe_image for a neutral description of what is visible."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to an image file within the workspace.",
            },
            "prompt": {
                "type": "string",
                "description": (
                    "Specific analysis instruction, question, or classification rule to apply to the image; "
                    "not a generic request to describe what is visible."
                ),
            },
        },
        "required": ["path", "prompt"],
        "additionalProperties": False,
    },
)


def build_analyze_image_tool(image_service: ImageService) -> Tool:
    async def analyze_image_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
        del signal
        path = args.get("path")
        prompt = args.get("prompt")
        if not isinstance(path, str) or path.strip() == "":
            return tool_error(
                "analyze_image expects a non-empty string argument: 'path'.",
                hint="Podaj pole 'path' jako ścieżkę do pliku graficznego w workspace.",
                details={
                    "received": {"path": path},
                    "expected": {"path": "non-empty string"},
                },
            )
        if not isinstance(prompt, str) or prompt.strip() == "":
            return tool_error(
                "analyze_image expects a non-empty string argument: 'prompt'.",
                hint="Podaj pole 'prompt' z instrukcją klasyfikacji lub analizy zdjęcia.",
                details={
                    "received": {"prompt": prompt},
                    "expected": {"prompt": "non-empty string"},
                },
            )

        analysis = await image_service.analyze_image(path, prompt)
        return tool_ok(analysis)

    return Tool(
        type="sync",
        definition=ANALYZE_IMAGE_DEFINITION,
        handler=analyze_image_handler,
    )
