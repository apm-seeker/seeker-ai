from langchain_core.runnables import Runnable
from langgraph.prebuilt import create_react_agent

from app.llm.provider import build_llm
from app.tools.seeker_tools import SEEKER_TOOLS

_graph: Runnable | None = None


def build_graph() -> Runnable:
    global _graph
    if _graph is None:
        llm = build_llm()
        _graph = create_react_agent(model=llm, tools=SEEKER_TOOLS)
    return _graph


def reset_graph() -> None:
    global _graph
    _graph = None
