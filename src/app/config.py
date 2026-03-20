from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Manfred API"
    VERSION: str = "0.0.0-dev"
    DESCRIPTION: str = "Agent API"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 3000
    API_RELOAD: bool = True
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s %(levelname)s %(name)s %(message)s"
    TOOL_LOG_MAX_LENGTH: int = 4000
    DATABASE_URL: str = "sqlite:///./manfred.db"
    AGENT_MAX_TURNS: int = 10
    LLM_TIMEOUT_SECONDS: int = 120
    LLM_PROVIDER: str = "openrouter"

#agent config
    SYSTEM_PROMPT_PATH: str = "app/agent/prompts/system_prompt.md"
# optional temperature etc

    OPENAI_URL: str = "https://api.openai.com/v1"
    OPENAI_API_KEY: str = ""
    OPENAI_LLM_MODEL: str = "gpt-4o-mini"
    OPENAI_VISION_MODEL: str = "gpt-4.1-mini"
    OPENAI_IMAGE_MODEL: str = "gpt-image-1.5"
    OPENAI_IMAGE_SIZE: str = "1024x1024"
    OPENAI_IMAGE_TIMEOUT_SECONDS: int = 120
    OPEN_ROUTER_URL: str = "https://openrouter.ai/api/v1"
    OPEN_ROUTER_API_KEY: str = ""
    OPEN_ROUTER_LLM_MODEL: str = "openai/gpt-4o-mini"
    OPEN_ROUTER_SLM_MODEL: str = "openai/gpt-4o-mini"
    ELEVENLABS_URL: str = "https://api.elevenlabs.io"
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_TRANSCRIPTION_MODEL: str = "scribe_v2"
    ELEVENLABS_TEXT_TO_SPEECH_MODEL: str = "eleven_multilingual_v2"
    ELEVENLABS_VOICE_ID: str = ""
    ELEVENLABS_OUTPUT_FORMAT: str = "mp3_44100_128"
    ELEVENLABS_TIMEOUT_SECONDS: int = 120
    DEFAULT_USER_ID: str = "default-user"
    DEFAULT_USER_NAME: str = "Default User"

    #gemini? TODO

    #openai TODO
    
    LANGFUSE_ENABLED: bool = True
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    LANGFUSE_ENVIRONMENT: str = "development"

    AI_DEVS_API_KEY: str = ""
    AI_DEVS_HUB_URL: str = "https://hub.ag3nts.org"
    WORKSPACE_ROOT: str = str(BASE_DIR / "workspace")
