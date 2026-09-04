from typing import Callable
from mistralai import Mistral
import os

from langchain.agents.middleware.types import ToolCallRequest, ModelResponse
from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage

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
    "Block a reply_to_comment call before it posts, if the drafted reply fails moderation."
    if request.tool_call["name"] != "reply_to_comment":
        return handler(request)

    message = request.tool_call["args"]["message"]
    if not _passes_moderation(message):
        return ToolMessage(
            content="Reply was blocked by moderation and not posted.",
            tool_call_id=request.tool_call["id"],
        )
    return handler(request)