from collections.abc import Callable
from pathlib import Path

from dependency_injector import containers, providers
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.agent.tools import calculator_tool
from app.domain.agent import AgentConfig
from app.domain.repositories import (
    AgentRepository,
    ItemRepository,
    SessionRepository,
    UserRepository,
)
from app.domain.tool import Tool, ToolRegistry
from app.services import ChatService


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


def get_tools() -> list[Tool]:
    return [calculator_tool]


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in get_tools():
        registry.register(tool)
    return registry


def build_agent_config(settings: Settings) -> AgentConfig:
    return AgentConfig(
        model=settings.OPEN_ROUTER_LLM_MODEL,
        task=load_system_prompt(settings.SYSTEM_PROMPT_PATH),
        tool_names=tuple(tool.definition.name for tool in get_tools()),
    )


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

    tool_registry = providers.Singleton(build_tool_registry)
    agent_config = providers.Singleton(build_agent_config, settings=settings)


    chat_service = providers.Factory(
        ChatService,
        user_repository=user_repository,
        session_repository=session_repository,
        agent_repository=agent_repository,
        item_repository=item_repository,
        agent_config=agent_config,
        tool_registry=tool_registry,
        default_user_id=settings.provided.DEFAULT_USER_ID,
        default_user_name=settings.provided.DEFAULT_USER_NAME,
    )
