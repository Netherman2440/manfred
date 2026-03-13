from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Manfred API"
    VERSION: str = "0.0.0-dev"
    DESCRIPTION: str = "Agent API built on LangGraph"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 3333
    REDIS_SAVER_CONNECTION_STRING: str = "redis://:change_me@127.0.0.1:6379/0"

    OPEN_ROUTER_URL: str = "https://openrouter.ai/api/v1"
    OPEN_ROUTER_API_KEY: str = ""
    OPEN_ROUTER_LLM_MODEL: str = "openai/gpt-4o-mini"
    OPEN_ROUTER_SLM_MODEL: str = "openai/gpt-4o-mini"
    LANGFUSE_ENABLED: bool = True
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    LANGFUSE_ENVIRONMENT: str = "development"
    SANDBOX_DIR: Path = Path("/home/netherman/code/manfred/src/sandbox")
