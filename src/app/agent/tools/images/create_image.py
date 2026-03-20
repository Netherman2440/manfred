from __future__ import annotations

from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool
from app.services.images import ImageService


CREATE_IMAGE_DEFINITION = FunctionToolDefinition(
    name="create_image",
    description="Generate an image from a text prompt using OpenAI and save the result in workspace/output.",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Prompt describing the image to generate.",
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    },
)


def build_create_image_tool(image_service: ImageService) -> Tool:
    async def create_image_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
        del signal
        prompt = args.get("prompt")
        if not isinstance(prompt, str) or prompt.strip() == "":
            raise ValueError("create_image expects a non-empty string argument: 'prompt'.")

        output_path = await image_service.create_image(prompt)
        return {"ok": True, "output": {"path": output_path}}

    return Tool(
        type="sync",
        definition=CREATE_IMAGE_DEFINITION,
        handler=create_image_handler,
    )
