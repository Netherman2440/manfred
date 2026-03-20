from __future__ import annotations

from typing import Any

from app.domain.tool import FunctionToolDefinition, Tool
from app.services.images import ImageService


DESCRIBE_IMAGE_DEFINITION = FunctionToolDefinition(
    name="describe_image",
    description="Describe what is visible in an image file from the workspace using OpenAI vision.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to an image file within the workspace.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
)


def build_describe_image_tool(image_service: ImageService) -> Tool:
    async def describe_image_handler(args: dict[str, Any], signal: object | None = None) -> dict[str, Any]:
        del signal
        path = args.get("path")
        if not isinstance(path, str) or path.strip() == "":
            raise ValueError("describe_image expects a non-empty string argument: 'path'.")

        description = await image_service.describe_image(path)
        return {"ok": True, "output": description}

    return Tool(
        type="sync",
        definition=DESCRIBE_IMAGE_DEFINITION,
        handler=describe_image_handler,
    )
