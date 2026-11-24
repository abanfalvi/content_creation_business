from pathlib import Path

from langchain.agents import create_agent
from langchain_openrouter import ChatOpenRouter

from ..models import CHAT_MODEL, track
from .state import QAChatAgentState
from .tools import QAChatAgentTools

SYSTEM_PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")

all_tools = [
    QAChatAgentTools.keyword_search_sources,
    QAChatAgentTools.semantic_search_sources,
    QAChatAgentTools.read_full_source,
]


def build_qa_chat_model() -> ChatOpenRouter:
    return ChatOpenRouter(model=CHAT_MODEL, temperature=0.3, timeout=180000)


def build_qa_chat_agent(model, checkpointer):
    return track(create_agent(
        model,
        tools=all_tools,
        state_schema=QAChatAgentState,
        system_prompt=SYSTEM_PROMPT,
        middleware=[],
        checkpointer=checkpointer,
    ))
