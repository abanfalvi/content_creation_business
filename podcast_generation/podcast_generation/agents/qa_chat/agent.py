from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.middleware import dynamic_prompt, ModelFallbackMiddleware
from langchain_openrouter import ChatOpenRouter
from langgraph.config import get_config

from ..models import CHAT_MODEL, track, FALLBACK_MODEL
from .state import QAChatAgentState
from .tools import QAChatAgentTools

SYSTEM_PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")

all_tools = [
    QAChatAgentTools.keyword_search_sources,
    QAChatAgentTools.semantic_search_sources,
    QAChatAgentTools.read_full_source,
    QAChatAgentTools.update_user_preference,
    QAChatAgentTools.forget_user_preference
]


@dynamic_prompt
def _prompt_with_context(_request) -> str:
    """Append the turn's selected-source note (built in ChatEngine.stream) to the static system prompt.

    Read from the run config so it is never written into the persisted thread and is recomputed each turn.
    """
    note = (get_config().get("configurable") or {}).get("source_note") or ""
    preference_note = (get_config().get("configurable") or {}).get("preference_note") or ""
    return "\n\n".join(part for part in (SYSTEM_PROMPT, note, preference_note) if part)


def build_qa_chat_model(model_name: str = CHAT_MODEL) -> ChatOpenRouter:
    return ChatOpenRouter(model=model_name, temperature=0.3, timeout=180000)


def build_qa_chat_agent(model, checkpointer):
    return track(create_agent(
        model,
        tools=all_tools,
        state_schema=QAChatAgentState,
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            _prompt_with_context,
            ModelFallbackMiddleware(
                first_model=build_qa_chat_model(FALLBACK_MODEL)
            )
        ],
        checkpointer=checkpointer,
    ))
