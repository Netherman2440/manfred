from pathlib import Path

from collections.abc import Callable

from dependency_injector import containers, providers
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings

from app.domain import Tool
from app.domain.repositories import (
    AgentRepository,
    ItemRepository,
    SessionRepository,
    UserRepository,
)
from app.providers import OpenRouterProvider, ProviderRegistry
from app.services.agent_loader import AgentLoader
from app.services.chat_service import ChatService
from app.tools.definitions.calculator import calculator_tool
from app.tools.registry import ToolRegistry


def build_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


def build_session_factory(engine: Engine) -> Callable[[], Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def build_db_session(session_factory: Callable[[], Session]) -> Session:
    return session_factory()


def get_tools() -> list[Tool]:
    return [calculator_tool]


def build_provider_registry(openrouter_provider: OpenRouterProvider) -> ProviderRegistry:
    return ProviderRegistry(
        providers={
            "openrouter": openrouter_provider,
        }
    )


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]



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
    db_session = providers.Factory(build_db_session, session_factory=session_factory)

    user_repository = providers.Factory(UserRepository, session=db_session)
    session_repository = providers.Factory(SessionRepository, session=db_session)
    agent_repository = providers.Factory(AgentRepository, session=db_session)
    item_repository = providers.Factory(ItemRepository, session=db_session)

    tool_registry = providers.Singleton(
        ToolRegistry,
        tools=providers.Callable(get_tools),
    )

    openrouter_provider = providers.Singleton(
        OpenRouterProvider,
        base_url=settings.provided.OPEN_ROUTER_URL,
        api_key=settings.provided.OPEN_ROUTER_API_KEY,
    )
    provider_registry = providers.Singleton(
        build_provider_registry,
        openrouter_provider=openrouter_provider,
    )
    agent_loader = providers.Singleton(
        AgentLoader,
        tool_registry=tool_registry,
        repo_root=providers.Callable(get_repo_root),
    )
    chat_service = providers.Factory(
        ChatService,
        session=db_session,
        settings=settings,
        tool_registry=tool_registry,
        provider_registry=provider_registry,
        agent_loader=agent_loader,
    )
