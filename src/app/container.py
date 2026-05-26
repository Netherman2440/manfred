import httpx
from dependency_injector import containers, providers
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.domain import Tool
from app.events import EventBus
from app.events.subscribers import ObserverSubscriber, ReflectorSubscriber
from app.mcp import StdioMcpManager
from app.observability import MarkdownEventLogger, SessionWorkspaceResolver, build_langfuse_subscriber
from app.providers import OpenRouterProvider, ProviderRegistry
from app.runtime.background_tasks import BackgroundTaskRegistry
from app.runtime.cancellation import ActiveRunRegistry
from app.services.agent_loader import AgentLoader
from app.services.agent_template_service import AgentTemplateService
from app.services.aidevs.negotiations import BaseNegotiationsService, NegotiationsService
from app.services.chat_attachments import ChatAttachmentStorageService
from app.services.chat_service import ChatService
from app.services.filesystem import AgentFilesystemService
from app.services.lock_service import LockService
from app.services.memory import (
    MemoryPathResolver,
    MemoryService,
    MemoryTokenCounter,
    ObserveUseCase,
)
from app.services.model_catalog_service import ModelCatalogService
from app.services.sensors import BaseSensorService, SensorService
from app.services.session_query_service import SessionQueryService
from app.services.tiktokenizer import TiktokenizerService
from app.services.tool_catalog_service import ToolCatalogService
from app.services.web_scraper import BaseWebScraperService, FirecrawlScraperService
from app.services.workspace_layout import WorkspaceLayoutService
from app.tools.definitions.aidevs import (
    build_execute_cmd_tool,
    build_fetch_aidevs_data_tool,
    build_mail_api_tool,
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
from app.tools.definitions.get_broken_sensors import build_get_broken_sensors_tool
from app.tools.definitions.get_sensors import build_get_sensors_tool
from app.tools.definitions.interprete_image import build_interprete_image_tool
from app.tools.definitions.message import message_tool
from app.tools.definitions.negotiations import (
    build_get_cities_for_item_tool,
    build_get_items_for_city_tool,
    build_list_cities_tool,
    build_list_items_tool,
)
from app.tools.definitions.scrape_url import build_scrape_url_tool
from app.tools.definitions.wait import wait_tool
from app.tools.definitions.web_search import web_search_tool
from app.tools.registry import ToolRegistry
from app.utils.paths import default_user_workspace_path, get_repo_root, resolve_relative_path


def get_tools(
    filesystem_service: AgentFilesystemService,
    sensor_service: BaseSensorService,
    web_scraper_service: BaseWebScraperService,
    negotiations_service: BaseNegotiationsService,
    settings: Settings,
) -> list[Tool]:
    return [
        calculator_tool,
        delegate_tool,
        ask_user_tool,
        message_tool,
        wait_tool,
        web_search_tool,
        build_scrape_url_tool(web_scraper_service),
        build_read_file_tool(filesystem_service),
        build_search_file_tool(filesystem_service),
        build_write_file_tool(filesystem_service),
        build_manage_file_tool(filesystem_service),
        build_submit_task_tool(settings),
        build_fetch_aidevs_data_tool(settings),
        build_mail_api_tool(settings),
        build_execute_cmd_tool(settings),
        build_interprete_image_tool(settings),
        build_get_sensors_tool(sensor_service),
        build_get_broken_sensors_tool(sensor_service),
        build_list_cities_tool(negotiations_service),
        build_list_items_tool(negotiations_service),
        build_get_cities_for_item_tool(negotiations_service),
        build_get_items_for_city_tool(negotiations_service),
    ]


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(
        packages=[
            "app",
            "app.api.v1",
            "app.api.v1.agents",
            "app.api.v1.chat",
            "app.api.v1.models",
            "app.api.v1.negotiations",
            "app.api.v1.tools",
            "app.api.v1.users",
        ],
    )

    settings = providers.Singleton(Settings)
    db_engine = providers.Singleton(
        create_engine,
        settings.provided.DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
    session_factory = providers.Singleton(
        sessionmaker,
        bind=db_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    db_session = providers.Factory(session_factory.provided.call())

    repo_root = providers.Callable(get_repo_root)

    workspace_layout_service = providers.Singleton(
        WorkspaceLayoutService,
        repo_root=repo_root,
        workspace_path=settings.provided.WORKSPACE_PATH,
        agent_mount_names=settings.provided.mount_names.call(),
        default_agent_source_dir=providers.Callable(
            lambda settings, repo_root: repo_root / settings.DEFAULT_AGENT_SOURCE_DIR,
            settings=settings,
            repo_root=repo_root,
        ),
        default_agent_name=settings.provided.DEFAULT_AGENT,
        files_dir_name=settings.provided.FILES_DIR_NAME,
        attachments_dir_name=settings.provided.ATTACHMENTS_DIR_NAME,
        plan_file_name=settings.provided.PLAN_FILE_NAME,
    )
    chat_attachment_storage_service = providers.Singleton(
        ChatAttachmentStorageService,
        workspace_layout_service=workspace_layout_service,
        max_file_size=settings.provided.MAX_FILE_SIZE,
    )
    filesystem_service = providers.Singleton(
        AgentFilesystemService,
        workspace_layout_service=workspace_layout_service,
        mount_names=settings.provided.mount_names.call(),
        max_file_size=settings.provided.MAX_FILE_SIZE,
        exclude_patterns=settings.provided.filesystem_exclude_patterns.call(),
    )
    sensor_service = providers.Singleton(
        SensorService,
        sensors_dir=providers.Callable(
            lambda repo_root, settings: (
                repo_root
                / settings.WORKSPACE_PATH
                / settings.DEFAULT_USER_ID
                / "shared"
                / "aidevs"
                / "data"
                / "sensors"
            ),
            repo_root=repo_root,
            settings=settings,
        ),
    )
    negotiations_service = providers.Singleton(
        NegotiationsService,
        csv_dir=providers.Callable(
            lambda repo_root: repo_root / "resources" / "negotiations",
            repo_root=repo_root,
        ),
    )
    web_scraper_service = providers.Singleton(
        FirecrawlScraperService,
        api_key=settings.provided.FIRECRAWL_API_KEY,
    )
    tool_registry = providers.Singleton(
        ToolRegistry,
        tools=providers.Callable(
            get_tools,
            filesystem_service=filesystem_service,
            sensor_service=sensor_service,
            web_scraper_service=web_scraper_service,
            negotiations_service=negotiations_service,
            settings=settings,
        ),
    )
    event_bus = providers.Singleton(EventBus)
    langfuse_subscriber = providers.Singleton(
        build_langfuse_subscriber,
        settings=settings,
    )
    session_workspace_resolver = providers.Singleton(
        SessionWorkspaceResolver,
        session_factory=session_factory,
    )
    markdown_event_logger = providers.Singleton(
        MarkdownEventLogger,
        workspace_resolver=session_workspace_resolver,
    )
    active_run_registry = providers.Singleton(ActiveRunRegistry)
    background_task_registry = providers.Singleton(BackgroundTaskRegistry)

    openrouter_provider = providers.Singleton(
        OpenRouterProvider,
        base_url=settings.provided.OPEN_ROUTER_URL,
        api_key=settings.provided.OPEN_ROUTER_API_KEY,
    )
    provider_registry = providers.Singleton(
        ProviderRegistry,
        providers=providers.Dict(openrouter=openrouter_provider),
    )
    mcp_config_path = providers.Callable(
        resolve_relative_path,
        settings.provided.MCP_CONFIG_PATH,
        base=repo_root,
    )
    mcp_manager = providers.Singleton(
        StdioMcpManager,
        repo_root=repo_root,
        config_path=mcp_config_path,
        client_name="manfred",
        client_version=settings.provided.VERSION,
        request_timeout_seconds=providers.Callable(
            lambda ms: ms / 1000,
            ms=settings.provided.MCP_TOOL_TIMEOUT_MS,
        ),
    )
    agent_loader = providers.Singleton(
        AgentLoader,
        tool_registry=tool_registry,
        mcp_manager=mcp_manager,
        repo_root=repo_root,
        workspace_path=providers.Callable(
            default_user_workspace_path,
            workspace_layout_service=workspace_layout_service,
            default_user_id=settings.provided.DEFAULT_USER_ID,
            default_user_name=settings.provided.DEFAULT_USER_NAME,
        ),
    )

    tiktokenizer_service = providers.Singleton(TiktokenizerService)
    lock_service = providers.Singleton(LockService)
    memory_token_counter = providers.Singleton(
        MemoryTokenCounter,
        tokenizer=tiktokenizer_service,
    )
    memory_service = providers.Singleton(
        MemoryService,
        provider=openrouter_provider,
        model=settings.provided.OBSERVER_LLM_MODEL,
    )
    memory_path_resolver = providers.Singleton(
        MemoryPathResolver,
        workspace_layout_service=workspace_layout_service,
        session_factory=session_factory,
    )
    observe_use_case = providers.Singleton(
        ObserveUseCase,
        memory_service=memory_service,
        token_counter=memory_token_counter,
        session_factory=session_factory,
        event_bus=event_bus,
        lock_service=lock_service,
        memory_path_resolver=memory_path_resolver,
        tokens_to_observe=settings.provided.TOKENS_TO_OBSERVE,
    )
    observer_subscriber = providers.Singleton(
        ObserverSubscriber,
        settings=settings,
        observe_use_case=observe_use_case,
        background_task_registry=background_task_registry,
    )
    reflector_subscriber = providers.Singleton(
        ReflectorSubscriber,
        settings=settings,
        session_factory=session_factory,
        memory_service=memory_service,
        token_counter=memory_token_counter,
        event_bus=event_bus,
        lock_service=lock_service,
        memory_path_resolver=memory_path_resolver,
        background_task_registry=background_task_registry,
    )

    chat_service = providers.Factory(
        ChatService,
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
        memory_path_resolver=memory_path_resolver,
        observe_use_case=observe_use_case,
    )
    session_query_service = providers.Factory(
        SessionQueryService,
        session=db_session,
    )

    http_client = providers.Singleton(httpx.AsyncClient)

    agent_template_service = providers.Factory(
        AgentTemplateService,
        agent_loader=agent_loader,
        workspace_layout_service=workspace_layout_service,
        db_session=db_session,
    )

    tool_catalog_service = providers.Singleton(
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
