from __future__ import annotations

import re

from app.config import Settings

REQUEST_TIMEOUT = 30.0
FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
SESSION_FILES_DIRNAME = "files"


def require_api_key(settings: Settings) -> str:
    api_key = settings.AI_DEVS_API_KEY.strip()
    if not api_key:
        raise ValueError("AI_DEVS_API_KEY is not configured — set it in .env")
    return api_key


def hub_base(settings: Settings) -> str:
    return settings.AI_DEVS_HUB_URL.rstrip("/")
