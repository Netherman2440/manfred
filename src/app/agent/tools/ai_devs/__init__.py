from app.agent.tools.ai_devs.verify_task import build_verify_task_tool
from app.config import Settings


def build_ai_devs_tools(settings: Settings):
    return [build_verify_task_tool(settings)]


__all__ = [
    "build_ai_devs_tools",
    "build_verify_task_tool",
]
