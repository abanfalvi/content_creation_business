"""Shared logic behind the `compact_context_window` tool of the content specialists.

Each specialist keeps its own compression prompt (what to record differs per agent) and
a thin tool that calls `compact_context`. The tool replaces the whole message history with
one structured memory entry, so the agent decides when to compact instead of a middleware
trimming the history at a fixed token count.
"""
from langchain.tools import ToolRuntime
from langchain_core.messages import (
    BaseMessage, HumanMessage, RemoveMessage, ToolMessage, get_buffer_string,
)
from langchain_core.runnables import RunnableConfig
from langchain_openrouter import ChatOpenRouter
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.types import Command
from typing import Sequence

from ..models import COMPRESSOR_MODEL

MIN_HISTORY_TO_COMPRESS = 6

compression_model = ChatOpenRouter(model=COMPRESSOR_MODEL, temperature=.3, max_tokens=10_000)


def summarise_messages(history: Sequence[BaseMessage], compression_prompt: str, config: RunnableConfig) -> str:
    formatted = get_buffer_string(history)
    response = compression_model.invoke(compression_prompt.replace("{message}", formatted), config)
    return response.content


def compact_context(runtime: ToolRuntime, compression_prompt: str) -> Command | str:
    """Body of a `compact_context_window` tool: summarise the history and replace it."""
    messages = runtime.state.get("messages")

    current_call = messages[len(messages) - 1]
    history = messages[:-1]

    if len(getattr(current_call, "tool_calls", None) or []) > 1:
        return "Error: call compact_context_window on its own, in a turn with no other tool calls. Nothing was compressed."

    if len(history) <= MIN_HISTORY_TO_COMPRESS:
        return "Not enough history to compress. Cannot compact your context window. Try to call this tool later."

    summary = summarise_messages(history, compression_prompt, runtime.config)
    summary_message = HumanMessage(f"Here is a summary of the conversation so far, replacing the earlier messages that were compressed:\n\n{summary}")

    return Command(
        update={
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                summary_message,
                current_call,
                ToolMessage(
                    content=f"Context compressed: {len(history)} message(s) condensed into the summary above.",
                    tool_call_id=runtime.tool_call_id,
                )
            ]
        }
    )
