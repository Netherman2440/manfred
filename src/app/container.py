from collections.abc import Callable

from dependency_injector import containers, providers
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings

from app.domain import AgentConfig, Tool, ToolRegistry
from app.domain.repositories import (
    AgentRepository,
    ItemRepository,
    SessionRepository,
    UserRepository,
)


def build_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


def build_session_factory(engine: Engine) -> Callable[[], Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def build_db_session(session_factory: Callable[[], Session]) -> Session:
    return session_factory()


def get_tools() -> list[Tool]:
    return []



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

    user_repository = providers.Factory(UserRepository)
    session_repository = providers.Factory(SessionRepository)
    agent_repository = providers.Factory(AgentRepository)
    item_repository = providers.Factory(ItemRepository)

    tool_registry = providers.Singleton(
        ToolRegistry,
        get_tools
    )
    
