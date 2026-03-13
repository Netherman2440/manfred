from collections.abc import AsyncIterator

from dependency_injector import containers, providers
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.graph.state import CompiledStateGraph
from langchain_openai import ChatOpenAI

from app.chat.graph_builder import GraphBuilder
from app.chat.tools.files import FileTools
from app.core.config import Settings
from app.observability.langfuse_service import LangfuseService


async def create_async_redis_saver(settings: Settings) -> AsyncIterator[AsyncRedisSaver]:
    saver = AsyncRedisSaver(
        redis_url=settings.REDIS_SAVER_CONNECTION_STRING,
    )
    await saver.asetup()

    try:
        yield saver
    finally:
        await saver.__aexit__(None, None, None)


def create_graph(
    graph_builder: GraphBuilder,
) -> CompiledStateGraph:
    return graph_builder.build()


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(
        packages=[
            "app",
            "app.chat",
            "app.api.v1",
            "app.api.v1.chat",
        ],
    )

    settings: providers.Singleton[Settings] = providers.Singleton(Settings)

    langfuse_service = providers.Singleton(
        LangfuseService,
        public_key=settings.provided.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.provided.LANGFUSE_SECRET_KEY,
        base_url=settings.provided.LANGFUSE_HOST,
        environment=settings.provided.LANGFUSE_ENVIRONMENT,
        release=settings.provided.VERSION,
        enabled=settings.provided.LANGFUSE_ENABLED,
    )

    llm: providers.Singleton[BaseChatModel] = providers.Singleton(
        ChatOpenAI,
        model=settings.provided.OPEN_ROUTER_LLM_MODEL,
        api_key=settings.provided.OPEN_ROUTER_API_KEY,
        base_url=settings.provided.OPEN_ROUTER_URL,
    )

    slm: providers.Singleton[BaseChatModel] = providers.Singleton(
        ChatOpenAI,
        model=settings.provided.OPEN_ROUTER_SLM_MODEL,
        api_key=settings.provided.OPEN_ROUTER_API_KEY,
        base_url=settings.provided.OPEN_ROUTER_URL,
    )

    file_tools = providers.Singleton(
        FileTools,
        sandbox_dir=settings.provided.SANDBOX_DIR,
    )

    tools = providers.Callable(
        lambda file_tools: file_tools.tools,
        file_tools,
    )

    async_redis_saver = providers.Resource(
        create_async_redis_saver,
        settings=settings,
    )

    graph_builder = providers.Factory(
        GraphBuilder,
        llm=llm,
        slm=slm,
        tools=tools,
        langfuse_service=langfuse_service,
        checkpointer=async_redis_saver,
    )

    graph: providers.Singleton[CompiledStateGraph] = providers.Singleton(
        create_graph,
        graph_builder=graph_builder,
    )
