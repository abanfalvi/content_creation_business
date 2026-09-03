from typing import Any, Callable
from mistralai import Mistral
import os

from langchain.agents.middleware.types import ToolCallRequest, ModelResponse
from langchain.agents.middleware import wrap_tool_call, before_model
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from langchain_huggingface import HuggingFaceEndpoint

from .state import EngagementState

from ...models import PROMPT_GUARD

mistral_client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

def _passes_moderation(text: str) -> bool:
    result = mistral_client.classifiers.moderate(model=PROMPT_GUARD, inputs=[text])
    scores = result.results[0].category_scores
    return max(scores.values()) < 0.4 


@wrap_tool_call
def moderate_reply(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ModelResponse],
) -> ModelResponse:
    """Configure agent behavior based on the current step."""
    if request.tool_call["name"] != "reply_to_comment":
        return handler(request)

    message = request.tool_call["args"]["messages"]
    if not _passes_moderation(message):
        return ToolMessage(
            content="Reply was blocked by moderation and not posted.",
            tool_call_id=request.tool_call["id"],
        )
    return handler(request)

@before_model
def input_guard(state: EngagementState, runtime: Runtime):
    last = state["messages"][-1]
    if not isinstance(last, ToolMessage):
        return None
    
    tool_name = last.name
    if tool_name != "reply_to_comment":
        return None
    
    tool_output = last.content
    if _passes_moderation(tool_output):
        return None
    return Command(update={
        "messages":[ToolMessage(content="The input content has been flagged as dangerous, hence could not be provided. Answer to a differnt comment", tool_call_id=state["messages"][-1].tool_call_id)]
    })