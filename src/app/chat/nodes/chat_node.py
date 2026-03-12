from langchain_core.language_models import BaseChatModel

from app.chat.state import GraphState


class ChatNode:
    def __init__(self, llm: BaseChatModel, tools: list) -> None:
        self._llm = llm
        self._tools = tools

    async def __call__(self, state: GraphState) -> dict:
        response = await self._llm.bind_tools(self._tools).ainvoke(state["messages"])
        return {"messages": [response]}
