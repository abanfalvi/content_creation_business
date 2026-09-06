from typing import Any, Awaitable, Callable

from langchain.agents.middleware import wrap_model_call, after_agent, wrap_tool_call
from langchain.agents.middleware.pii import detect_email
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage, HumanMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

from .state import ManagerState
from .tools import ManagerTools

STEP_CONFIG = {
    "content_creation": {
        "tools": [
            ManagerTools.call_content_strategist_agent,
            ManagerTools.call_sm_content_writer_agent,
            ManagerTools.read_content_calendar,
            ManagerTools.mark_posted
        ]
    },
    "trace_auditing": {
        "tools": [ManagerTools.call_auditor]
    }
}


def _redact(text: str) -> str:
    matches = detect_email(text)
    for m in sorted(matches, key=lambda m: m["start"], reverse=True):
        text = text[: m["start"]] + f"[REDACTED_{m['type'].upper()}]" + text[m["end"] :]
    return text


@wrap_model_call
async def apply_step_config(
    request: ModelRequest,
    handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
) -> ModelResponse:
    """Configure agent behavior based on the current step."""
    active_agent = request.state.get("active_step")

    # Look up step configuration
    stage_config = STEP_CONFIG[active_agent]

    # Inject system prompt and step-specific tools
    request = request.override(
        tools=stage_config["tools"],
    )

    return await handler(request)


@wrap_tool_call
async def redact_buffer_get_account_output(
    request: ModelRequest,
    handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
) -> ModelResponse:
    result = await handler(request)
    if request.tool_call["name"] != "get_account":
        return result
    if isinstance(result, ToolMessage) and result.content:
        return result.model_copy(update={"content": _redact(str(result.content))})
    if isinstance(result, Command) and result.update.get("messages"):
        msgs = list(result.update["messages"])
        msgs[0] = msgs[0].model_copy(update={"content": _redact(str(msgs[0].content))})
        return Command(update={**result.update, "messages": msgs})
    return result


MAX_VERIFY_END_RETRIES = 3


@after_agent(can_jump_to=["model"])
def verify_end(state: ManagerState, runtime: Runtime) -> dict[str, Any] | None:
    past_messages = state.get("messages", [])
    last_tool_message = next((m for m in reversed(past_messages) if isinstance(m, ToolMessage)), None)
    if last_tool_message is None or last_tool_message.name in [
        "call_content_strategist_agent", "call_sm_content_writer_agent", "call_auditor", "mark_posted"
    ]:
        # Reset so a later task in the same thread starts this count fresh.
        return {"verify_end_retries": 0} if state.get("verify_end_retries") else None

    retries = state.get("verify_end_retries", 0) + 1
    if retries > MAX_VERIFY_END_RETRIES:
        return {"verify_end_retries": 0}

    return {
        "jump_to": "model",
        "verify_end_retries": retries,
        "messages": [
            HumanMessage(content=(
                "Your last tool call was not directed to call_content_strategist_agent, "
                "call_sm_content_writer_agent, or call_auditor. Your task might not be finished yet!"
            ))
        ],
    }
