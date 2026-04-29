from collections.abc import Callable
from pathlib import Path

from dependency_injector import containers, providers
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.domain import Tool
from app.domain.repositories import AgentRepository, ItemRepository, SessionRepository, UserRepository
from app.events import EventBus
from app.services.filesystem import (
    AgentFilesystemService,
    FilesystemPathResolver,
    UserScopedWorkspaceFilesystemPolicy,
    build_filesystem_mounts,
)
from app.mcp import StdioMcpManager
from app.observability import build_langfuse_subscriber
from app.providers import OpenRouterProvider, ProviderRegistry
from app.runtime.cancellation import ActiveRunRegistry
from app.runtime.runner import Runner
from app.services.agent_loader import AgentLoader
from app.services.chat_service import ChatService
from app.services.session_query_service import SessionQueryService
from app.tools.definitions.ask_user import ask_user_tool
from app.tools.definitions.calculator import calculator_tool
from app.tools.definitions.delegate import delegate_tool
from app.tools.definitions.filesystem import (
    build_manage_file_tool,
    build_read_file_tool,
    build_search_file_tool,
    build_write_file_tool,
)
from app.tools.registry import ToolRegistry


def build_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


def build_session_factory(engine: Engine) -> Callable[[], Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def build_db_session(session_factory: Callable[[], Session]) -> Session:
    return session_factory()


def build_filesystem_service(
    *,
    settings: Settings,
    repo_root: Path,
) -> AgentFilesystemService:
    mounts = build_filesystem_mounts(
        repo_root=repo_root,
        fs_roots=settings.filesystem_roots(),
        workspace_path=settings.WORKSPACE_PATH,
    )
    path_resolver = FilesystemPathResolver(mounts, workspace_root=settings.WORKSPACE_PATH)
    workspace_mount_names = {
        mount.name
        for mount in mounts
        if mount.name == "workspaces" or mount.name.endswith("/workspaces")
    }
    access_policy = UserScopedWorkspaceFilesystemPolicy(
        workspace_mount_names=workspace_mount_names,
    )
    return AgentFilesystemService(
        path_resolver=path_resolver,
        access_policy=access_policy,
        max_file_size=settings.MAX_FILE_SIZE,
        exclude_patterns=settings.filesystem_exclude_patterns(),
    )


def get_tools(filesystem_service: AgentFilesystemService) -> list[Tool]:
    return [
        calculator_tool,
        delegate_tool,
        ask_user_tool,
        build_read_file_tool(filesystem_service),
        build_search_file_tool(filesystem_service),
        build_write_file_tool(filesystem_service),
        build_manage_file_tool(filesystem_service),
    ]


def build_provider_registry(openrouter_provider: OpenRouterProvider) -> ProviderRegistry:
    return ProviderRegistry(providers={"openrouter": openrouter_provider})


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_mcp_manager(
    *,
    settings: Settings,
    repo_root: Path,
) -> StdioMcpManager:
    config_path = Path(settings.MCP_CONFIG_PATH)
    if not config_path.is_absolute():
        config_path = repo_root / config_path

    return StdioMcpManager(
        repo_root=repo_root,
        config_path=config_path.resolve(),
        client_name="manfred",
        client_version=settings.VERSION,
        request_timeout_seconds=settings.MCP_TOOL_TIMEOUT_MS / 1000,
    )


def build_runner(
    *,
    session: Session,
    settings: Settings,
    tool_registry: ToolRegistry,
    mcp_manager: StdioMcpManager,
    provider_registry: ProviderRegistry,
    event_bus: EventBus,
    agent_loader: AgentLoader,
) -> Runner:
    return Runner(
        agent_repository=AgentRepository(session),
        session_repository=SessionRepository(session),
        item_repository=ItemRepository(session),
        tool_registry=tool_registry,
        mcp_manager=mcp_manager,
        provider_registry=provider_registry,
        event_bus=event_bus,
        agent_loader=agent_loader,
        max_delegation_depth=settings.MAX_DELEGATION_DEPTH,
    )


def build_chat_service(
    *,
    session: Session,
    settings: Settings,
    agent_loader: AgentLoader,
    tool_registry: ToolRegistry,
    mcp_manager: StdioMcpManager,
    provider_registry: ProviderRegistry,
    event_bus: EventBus,
    active_run_registry: ActiveRunRegistry,
) -> ChatService:
    user_repository = UserRepository(session)
    session_repository = SessionRepository(session)
    agent_repository = AgentRepository(session)
    item_repository = ItemRepository(session)

    return ChatService(
        session=session,
        settings=settings,
        agent_loader=agent_loader,
        user_repository=user_repository,
        session_repository=session_repository,
        agent_repository=agent_repository,
        item_repository=item_repository,
        runner=build_runner(
            session=session,
            settings=settings,
            tool_registry=tool_registry,
            mcp_manager=mcp_manager,
            provider_registry=provider_registry,
            event_bus=event_bus,
            agent_loader=agent_loader,
        ),
        active_run_registry=active_run_registry,
    )


def build_session_query_service(*, session: Session) -> SessionQueryService:
    return SessionQueryService(
        session_repository=SessionRepository(session),
        agent_repository=AgentRepository(session),
        item_repository=ItemRepository(session),
    )


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(
        packages=[
            "app",
            "app.api.v1",
            "app.api.v1.chat",
            "app.api.v1.users",
        ],
    )

    settings = providers.Singleton(Settings)
    db_engine = providers.Singleton(build_engine, database_url=settings.provided.DATABASE_URL)
    session_factory = providers.Singleton(build_session_factory, engine=db_engine)
    db_session = providers.Factory(build_db_session, session_factory=session_factory)

    filesystem_service = providers.Singleton(
        build_filesystem_service,
        settings=settings,
        repo_root=providers.Callable(get_repo_root),
    )
    tool_registry = providers.Singleton(
        ToolRegistry,
        tools=providers.Callable(get_tools, filesystem_service=filesystem_service),
    )
    event_bus = providers.Singleton(EventBus)
    langfuse_subscriber = providers.Singleton(
        build_langfuse_subscriber,
        settings=settings,
    )
    active_run_registry = providers.Singleton(ActiveRunRegistry)

    openrouter_provider = providers.Singleton(
        OpenRouterProvider,
        base_url=settings.provided.OPEN_ROUTER_URL,
        api_key=settings.provided.OPEN_ROUTER_API_KEY,
    )
    provider_registry = providers.Singleton(
        build_provider_registry,
        openrouter_provider=openrouter_provider,
    )
    mcp_manager = providers.Singleton(
        build_mcp_manager,
        settings=settings,
        repo_root=providers.Callable(get_repo_root),
    )
    agent_loader = providers.Singleton(
        AgentLoader,
        tool_registry=tool_registry,
        mcp_manager=mcp_manager,
        repo_root=providers.Callable(get_repo_root),
        workspace_path=settings.provided.WORKSPACE_PATH,
    )

    chat_service = providers.Factory(
        build_chat_service,
        session=db_session,
        settings=settings,
        agent_loader=agent_loader,
        tool_registry=tool_registry,
        mcp_manager=mcp_manager,
        provider_registry=provider_registry,
        event_bus=event_bus,
        active_run_registry=active_run_registry,
    )
    session_query_service = providers.Factory(
        build_session_query_service,
        session=db_session,
    )
