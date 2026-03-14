from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.chat.nodes.chat_node import ChatNode
from app.chat.state import GraphState
from app.observability.langfuse_service import LangfuseService


class GraphBuilder:
    def __init__(
        self,
        llm: BaseChatModel,
        slm: BaseChatModel,
        tools: list,
        langfuse_service: LangfuseService,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self.llm = llm
        self.slm = slm
        self.tools = tools
        self.langfuse_service = langfuse_service
        self.checkpointer = checkpointer

    def build(self) -> CompiledStateGraph:
        workflow = StateGraph(GraphState)
        chat_node = ChatNode(
            llm=self.llm,
            tools=self.tools,
            langfuse_service=self.langfuse_service,
        )
        tool_node = ToolNode(self.tools)

        workflow.add_node("chat", chat_node)
        workflow.add_node("tools", tool_node)

        workflow.add_edge(START, "chat")
        workflow.add_conditional_edges(
            "chat",
            tools_condition,
            {
                "tools": "tools",
                END: END,
            },
        )
        workflow.add_edge("tools", "chat")

        return workflow.compile(checkpointer=self.checkpointer)
