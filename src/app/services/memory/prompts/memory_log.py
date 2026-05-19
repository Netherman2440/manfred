from __future__ import annotations


def memory_log_prompt(*, observations: str) -> str:
    """System-prompt fragment that exposes the agent's memory log."""
    return (
        "<memory-log>\n"
        "Below are observations summarising past interactions with this user. "
        "Use them as background. Newer messages always take priority.\n\n"
        f"{observations.strip()}\n"
        "</memory-log>"
    )


def current_task_block(*, current_task: str | None) -> str:
    if not current_task:
        return ""
    return f"<current-task>\n{current_task.strip()}\n</current-task>"


def memory_log_continuation() -> str:
    """User-role message injected before the latest user message.

    Prevents the model from awkwardly acknowledging the memory system.
    """
    return (
        "<system-reminder>Please continue naturally with the conversation so far "
        "and respond to the latest message.\n\n"
        "Use the earlier context only as background. If something appears unfinished, "
        "continue only when it helps answer the latest request.\n\n"
        "Do not mention internal instructions, memory, summarization, context handling, "
        "or missing messages.\n\n"
        "Any messages following this reminder are newer and should take priority."
        "</system-reminder>"
    )
