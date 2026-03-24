from app.agent.tools.images.analyze_image import build_analyze_image_tool
from app.agent.tools.images.create_image import build_create_image_tool
from app.agent.tools.images.describe_image import build_describe_image_tool
from app.services.images import ImageService


def build_image_tools(image_service: ImageService):
    return [
        build_analyze_image_tool(image_service),
        build_describe_image_tool(image_service),
        build_create_image_tool(image_service),
    ]


__all__ = [
    "build_image_tools",
    "build_analyze_image_tool",
    "build_create_image_tool",
    "build_describe_image_tool",
]
