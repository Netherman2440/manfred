from langgraph.graph import StateGraph, BaseChatModel
from app.chat.state import GraphState


class GraphBuilder:
    def __init__(self,
            llm: BaseChatModel,
            slm: BaseChatModel,
            tools: list,
            ):
            self.llm=llm
            self.slm=slm
            self.tools=tools
            

    def get_graph(self) -> StateGraph[GraphState]:

        workflow = StateGraph(GraphState)

        #TODO Agent node, Tool node

        return workflow

