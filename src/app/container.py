from collections.abc import Callable
from pathlib import Path

from dependency_injector import containers, providers
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import BASE_DIR, Settings
from app.agent.tools import build_ai_devs_tools, build_audio_tools, build_image_tools, calculator_tool, filesystem_tools
from app.db.repositories import (
    AgentRepository,
    ItemRepository,
    SessionRepository,
    UserRepository,
)
from app.domain import AgentConfig, Tool, ToolRegistry
from app.providers import OpenAIProvider, OpenAIProviderConfig
from app.runtime import AgentRunner
from app.services import AudioService, ElevenLabsAudioService, ImageService, OpenAIImageService
from app.services.chat_service import ChatService
from app.services.observability import build_observability_service


def build_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


def build_session_factory(engine: Engine) -> Callable[[], Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def load_system_prompt(path: str) -> str:
    prompt_path = Path(path)
    if not prompt_path.is_absolute():
        prompt_path = Path(__file__).resolve().parent.parent / path
    return prompt_path.read_text(encoding="utf-8").strip()


def resolve_workspace_root(raw_path: str) -> Path:
    workspace_root = Path(raw_path).expanduser()
    if not workspace_root.is_absolute():
        workspace_root = BASE_DIR / workspace_root
    return workspace_root.resolve(strict=False)


def build_audio_service(settings: Settings) -> AudioService:
    return ElevenLabsAudioService(
        base_url=settings.ELEVENLABS_URL,
        api_key=settings.ELEVENLABS_API_KEY,
        workspace_root=resolve_workspace_root(settings.WORKSPACE_ROOT),
        transcription_model=settings.ELEVENLABS_TRANSCRIPTION_MODEL,
        text_to_speech_model=settings.ELEVENLABS_TEXT_TO_SPEECH_MODEL,
        voice_id=settings.ELEVENLABS_VOICE_ID,
        output_format=settings.ELEVENLABS_OUTPUT_FORMAT,
        timeout_seconds=settings.ELEVENLABS_TIMEOUT_SECONDS,
    )


def build_image_service(settings: Settings) -> ImageService:
    return OpenAIImageService(
        base_url=settings.OPENAI_URL,
        api_key=settings.OPENAI_API_KEY,
        workspace_root=resolve_workspace_root(settings.WORKSPACE_ROOT),
        vision_model=settings.OPENAI_VISION_MODEL,
        image_model=settings.OPENAI_IMAGE_MODEL,
        image_size=settings.OPENAI_IMAGE_SIZE,
        timeout_seconds=settings.OPENAI_IMAGE_TIMEOUT_SECONDS,
    )


def get_tools(settings: Settings, audio_service: AudioService, image_service: ImageService) -> list[Tool]:
    return [
        calculator_tool,
        *filesystem_tools,
        *build_audio_tools(audio_service),
        *build_image_tools(image_service),
        *build_ai_devs_tools(settings),
    ]


def build_tool_registry(settings: Settings, audio_service: AudioService, image_service: ImageService) -> ToolRegistry:
    registry = ToolRegistry(max_log_value_length=settings.TOOL_LOG_MAX_LENGTH)
    for tool in get_tools(settings, audio_service, image_service):
        registry.register(tool)
    return registry


def build_agent_config(settings: Settings, audio_service: AudioService, image_service: ImageService) -> AgentConfig:
    if settings.LLM_PROVIDER == "openai":
        model = settings.OPENAI_LLM_MODEL
    elif settings.LLM_PROVIDER == "openrouter":
        model = settings.OPEN_ROUTER_LLM_MODEL
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {settings.LLM_PROVIDER}")

    return AgentConfig(
        model=model,
        task=load_system_prompt(settings.SYSTEM_PROMPT_PATH),
        tool_names=tuple(tool.definition.name for tool in get_tools(settings, audio_service, image_service)),
    )


def build_provider_config(settings: Settings) -> OpenAIProviderConfig:
    if settings.LLM_PROVIDER == "openai":
        return OpenAIProviderConfig(
            base_url=settings.OPENAI_URL,
            api_key=settings.OPENAI_API_KEY,
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
            provider_name="openai",
            app_name=settings.PROJECT_NAME,
        )

    if settings.LLM_PROVIDER == "openrouter":
        return OpenAIProviderConfig(
            base_url=settings.OPEN_ROUTER_URL,
            api_key=settings.OPEN_ROUTER_API_KEY,
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
            provider_name="openrouter",
            app_name=settings.PROJECT_NAME,
        )

    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.LLM_PROVIDER}")


def build_provider(config: OpenAIProviderConfig) -> OpenAIProvider:
    return OpenAIProvider(config)


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(
        packages=[
            "app",
            "app.api.v1",
            "app.api.v1.chat",
        ],
        )

    settings = providers.Singleton(Settings)
    db_engine = providers.Singleton(build_engine, database_url=settings.provided.DATABASE_URL)
    session_factory = providers.Singleton(build_session_factory, engine=db_engine)

    user_repository = providers.Factory(UserRepository, session_factory=session_factory)
    session_repository = providers.Factory(SessionRepository, session_factory=session_factory)
    agent_repository = providers.Factory(AgentRepository, session_factory=session_factory)
    item_repository = providers.Factory(ItemRepository, session_factory=session_factory)

    audio_service = providers.Singleton(build_audio_service, settings=settings)
    image_service = providers.Singleton(build_image_service, settings=settings)
    tool_registry = providers.Singleton(
        build_tool_registry,
        settings=settings,
        audio_service=audio_service,
        image_service=image_service,
    )
    agent_config = providers.Singleton(
        build_agent_config,
        settings=settings,
        audio_service=audio_service,
        image_service=image_service,
    )
    provider_config = providers.Singleton(build_provider_config, settings=settings)
    provider = providers.Singleton(build_provider, config=provider_config)
    observability_service = providers.Singleton(build_observability_service, settings=settings)
    agent_runner = providers.Factory(
        AgentRunner,
        agent_repository=agent_repository,
        session_repository=session_repository,
        item_repository=item_repository,
        tool_registry=tool_registry,
        provider=provider,
        observability=observability_service,
        max_turn_count=settings.provided.AGENT_MAX_TURNS,
    )


    chat_service = providers.Factory(
        ChatService,
        user_repository=user_repository,
        session_repository=session_repository,
        agent_repository=agent_repository,
        item_repository=item_repository,
        agent_config=agent_config,
        tool_registry=tool_registry,
        agent_runner=agent_runner,
        observability=observability_service,
        default_user_id=settings.provided.DEFAULT_USER_ID,
        default_user_name=settings.provided.DEFAULT_USER_NAME,
    )
