from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings


LOCALHOST_CORS_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"


def apply_cors_middleware(app: FastAPI, settings: Settings) -> None:
    cors_origins = parse_cors_origins(settings.API_CORS_ORIGINS)
    cors_origin_regex = get_cors_origin_regex(settings.API_CORS_ALLOW_LOCALHOST)
    if not cors_origins and not cors_origin_regex:
        return

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def parse_cors_origins(raw_origins: str) -> list[str]:
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


def get_cors_origin_regex(allow_localhost: bool) -> str | None:
    return LOCALHOST_CORS_ORIGIN_REGEX if allow_localhost else None
