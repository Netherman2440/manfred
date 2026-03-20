from __future__ import annotations

import logging

from app.config import Settings


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=_resolve_log_level(settings.LOG_LEVEL),
        format=settings.LOG_FORMAT,
        force=True,
    )


def _resolve_log_level(raw_level: str) -> int:
    level_name = raw_level.strip().upper()
    level = logging.getLevelName(level_name)
    if isinstance(level, int):
        return level
    return logging.INFO
