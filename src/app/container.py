from collections.abc import Callable
from pathlib import Path

import httpx
from dependency_injector import containers, providers
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.domain import Tool
from app.domain.repositories import (
    AgentRepository,
    ItemRepository,
    QueuedInputRepository,
    SessionRepository,
    UserRepository,
)
from app.events import EventBus
from app.mcp import StdioMcpManager
from app.observability import MarkdownEventLogger, build_langfuse_subscriber
from app.providers import OpenRouterProvider, ProviderRegistry
from app.runtime.cancellation import ActiveRunRegistry
from app.runtime.message_queue import SessionMessageQueue
from app.runtime.runner import Runner
from app.services.agent_loader import AgentLoader
from app.services.agent_template_service import AgentTemplateService
from app.services.chat_attachments import ChatAttachmentStorageService
from app.services.chat_service import ChatService
from app.services.filesystem import (
    AgentFilesystemService,
    FilesystemPathResolver,
    WorkspaceLayoutService,
    WorkspaceScopedFilesystemPolicy,
    build_mounts,
)
from app.services.model_catalog_service import ModelCatalogService
from app.services.session_query_service import SessionQueryService
from app.services.tiktokenizer_service import TiktokenizerService
from app.services.tool_catalog_service import ToolCatalogService
from app.tools.definitions.aidevs import (
    build_count_tokens_tool,
    build_fetch_aidevs_data_tool,
    build_fetch_log_tool,
    build_submit_task_tool,
)
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


def _resolve_fs_root(*, repo_root: Path, workspace_path: str) -> Path:
    root = Path(workspace_path)
    return (repo_root / root).resolve() if not root.is_absolute() else root.resolve()


def build_filesystem_service(
    *,
    settings: Settings,
    repo_root: Path,
    workspace_layout_service: WorkspaceLayoutService,
) -> AgentFilesystemService:
    fs_root = _resolve_fs_root(repo_root=repo_root, workspace_path=settings.WORKSPACE_PATH)
    mounts = build_mounts(mount_names=settings.mount_names(), fs_root=fs_root)
    path_resolver = FilesystemPathResolver(mounts)
    access_policy = WorkspaceScopedFilesystemPolicy(
        workspace_layout_service=workspace_layout_service,
        fs_root=fs_root,
    )
    return AgentFilesystemService(
        path_resolver=path_resolver,
        access_policy=access_policy,
        max_file_size=settings.MAX_FILE_SIZE,
        exclude_patterns=settings.filesystem_exclude_patterns(),
    )


def build_workspace_layout_service(
    *,
    settings: Settings,
    repo_root: Path,
    default_agent_source_dir: Path | None = None,
) -> WorkspaceLayoutService:
    return WorkspaceLayoutService(
        repo_root=repo_root,
        workspace_path=settings.WORKSPACE_PATH,
        agent_mount_names=settings.mount_names(),
        default_agent_source_dir=default_agent_source_dir,
        default_agent_name=settings.DEFAULT_AGENT,
        files_dir_name=settings.FILES_DIR_NAME,
        attachments_dir_name=settings.ATTACHMENTS_DIR_NAME,
        plan_file_name=settings.PLAN_FILE_NAME,
    )


def get_tools(
    filesystem_service: AgentFilesystemService,
    settings: Settings,
    tiktokenizer_service: TiktokenizerService,
) -> list[Tool]:
    return [
        calculator_tool,
        delegate_tool,
        ask_user_tool,
        build_read_file_tool(filesystem_service),
        build_search_file_tool(filesystem_service),
        build_write_file_tool(filesystem_service),
        build_manage_file_tool(filesystem_service),
        build_submit_task_tool(settings),
        build_fetch_aidevs_data_tool(settings),
        build_fetch_log_tool(settings),
        build_count_tokens_tool(tiktokenizer_service, filesystem_service),
    ]


def build_provider_registry(openrouter_provider: OpenRouterProvider) -> ProviderRegistry:
    return ProviderRegistry(providers={"openrouter": openrouter_provider})


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _build_agent_loader_workspace_path(*, settings: Settings, repo_root: Path) -> str:
    """Return the user workspace root path string for AgentLoader.
    Since this is a single-user app, compute user workspace key from default user settings.
    """
    from app.services.filesystem import WorkspaceLayoutService as _WLS  # local import to avoid circular

    wls = _WLS(repo_root=repo_root, workspace_path=settings.WORKSPACE_PATH)
    workspace_key = wls.resolve_user_workspace_key(
        user_id=settings.DEFAULT_USER_ID,
        user_name=settings.DEFAULT_USER_NAME,
    )
    root = Path(settings.WORKSPACE_PATH)
    if not root.is_absolute():
        root = (repo_root / root).resolve()
    else:
        root = root.resolve()
    return str(root / workspace_key)


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
    message_queue: SessionMessageQueue,
    filesystem_service: AgentFilesystemService,
) -> Runner:
    return Runner(
        agent_repository=AgentRepository(session),
        session_repository=SessionRepository(session),
        item_repository=ItemRepository(session),
        user_repository=UserRepository(session),
        tool_registry=tool_registry,
        mcp_manager=mcp_manager,
        provider_registry=provider_registry,
        event_bus=event_bus,
        agent_loader=agent_loader,
        max_delegation_depth=settings.MAX_DELEGATION_DEPTH,
        max_turns=settings.MAX_TURNS,
        message_queue=message_queue,
        filesystem_service=filesystem_service,
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
    workspace_layout_service: WorkspaceLayoutService,
    attachment_storage_service: ChatAttachmentStorageService,
    filesystem_service: AgentFilesystemService,
) -> ChatService:
    user_repository = UserRepository(session)
    session_repository = SessionRepository(session)
    agent_repository = AgentRepository(session)
    item_repository = ItemRepository(session)
    queued_input_repository = QueuedInputRepository(session)
    message_queue = SessionMessageQueue(
        queued_input_repository=queued_input_repository,
        item_repository=item_repository,
    )

    return ChatService(
        session=session,
        settings=settings,
        agent_loader=agent_loader,
        user_repository=user_repository,
        session_repository=session_repository,
        agent_repository=agent_repository,
        item_repository=item_repository,
        queued_input_repository=queued_input_repository,
        runner=build_runner(
            session=session,
            settings=settings,
            tool_registry=tool_registry,
            mcp_manager=mcp_manager,
            provider_registry=provider_registry,
            event_bus=event_bus,
            agent_loader=agent_loader,
            message_queue=message_queue,
            filesystem_service=filesystem_service,
        ),
        active_run_registry=active_run_registry,
        workspace_layout_service=workspace_layout_service,
        attachment_storage_service=attachment_storage_service,
        message_queue=message_queue,
    )


def build_session_query_service(*, session: Session) -> SessionQueryService:
    return SessionQueryService(
        session_repository=SessionRepository(session),
        agent_repository=AgentRepository(session),
        item_repository=ItemRepository(session),
    )


def build_markdown_event_logger(*, session_factory: Callable[[], Session]) -> MarkdownEventLogger:
    def resolver(session_id: str) -> Path | None:
        sa_session = session_factory()
        try:
            session = SessionRepository(sa_session).get(session_id)
            if session is None or not session.workspace_path:
                return None
            return Path(session.workspace_path)
        finally:
            sa_session.close()

    return MarkdownEventLogger(workspace_resolver=resolver)


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(
        packages=[
            "app",
            "app.api.v1",
            "app.api.v1.agents",
            "app.api.v1.chat",
            "app.api.v1.models",
            "app.api.v1.tools",
            "app.api.v1.users",
        ],
    )

    settings = providers.Singleton(Settings)
    db_engine = providers.Singleton(build_engine, database_url=settings.provided.DATABASE_URL)
    session_factory = providers.Singleton(build_session_factory, engine=db_engine)
    db_session = providers.Factory(build_db_session, session_factory=session_factory)

    repo_root = providers.Callable(get_repo_root)

    workspace_layout_service = providers.Singleton(
        build_workspace_layout_service,
        settings=settings,
        repo_root=repo_root,
        default_agent_source_dir=providers.Callable(
            lambda settings, repo_root: repo_root / settings.DEFAULT_AGENT_SOURCE_DIR,
            settings=settings,
            repo_root=repo_root,
        ),
    )
    chat_attachment_storage_service = providers.Singleton(
        ChatAttachmentStorageService,
        workspace_layout_service=workspace_layout_service,
        max_file_size=settings.provided.MAX_FILE_SIZE,
    )
    filesystem_service = providers.Singleton(
        build_filesystem_service,
        settings=settings,
        repo_root=repo_root,
        workspace_layout_service=workspace_layout_service,
    )
    tiktokenizer_service = providers.Singleton(TiktokenizerService)
    tool_registry = providers.Singleton(
        ToolRegistry,
        tools=providers.Callable(
            get_tools,
            filesystem_service=filesystem_service,
            settings=settings,
            tiktokenizer_service=tiktokenizer_service,
        ),
    )
    event_bus = providers.Singleton(EventBus)
    langfuse_subscriber = providers.Singleton(
        build_langfuse_subscriber,
        settings=settings,
    )
    markdown_event_logger = providers.Singleton(
        build_markdown_event_logger,
        session_factory=session_factory,
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
        repo_root=repo_root,
    )
    agent_loader = providers.Singleton(
        AgentLoader,
        tool_registry=tool_registry,
        mcp_manager=mcp_manager,
        repo_root=repo_root,
        workspace_path=providers.Callable(
            _build_agent_loader_workspace_path,
            settings=settings,
            repo_root=repo_root,
        ),
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
        workspace_layout_service=workspace_layout_service,
        attachment_storage_service=chat_attachment_storage_service,
        filesystem_service=filesystem_service,
    )
    session_query_service = providers.Factory(
        build_session_query_service,
        session=db_session,
    )

    http_client = providers.Singleton(httpx.AsyncClient)

    agent_template_service = providers.Factory(
        AgentTemplateService,
        agent_loader=agent_loader,
        workspace_layout_service=workspace_layout_service,
        db_session=db_session,
    )

    tool_catalog_service = providers.Factory(
        ToolCatalogService,
        tool_registry=tool_registry,
        mcp_manager=mcp_manager,
    )

    model_catalog_service = providers.Singleton(
        ModelCatalogService,
        http_client=http_client,
        api_url=settings.provided.OPEN_ROUTER_URL,
        api_key=settings.provided.OPEN_ROUTER_API_KEY,
    )
