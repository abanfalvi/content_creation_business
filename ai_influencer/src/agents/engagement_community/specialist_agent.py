# Content Strategist Agent
# Aim: Design the content calendar to follow

from dotenv import load_dotenv
from typing import Any, Callable
from opik.integrations.langchain import OpikTracer, track_langgraph

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware, wrap_model_call
from langchain.agents.middleware.types import ModelRequest, ModelResponse

from ...models import REPLY_AGENT
from .tools import AgentTools
from .state import EngagementState
from .guardrails import moderate_reply, input_guard
from .utils import checkpointer
from ...memory_store import shared_memory_store

load_dotenv()

response_handling_model = ChatOpenRouter(
    model=REPLY_AGENT,
    temperature=0.2,
    max_tokens=2048
)

with open(r"src\agents\engagement_community\SYSTEM_PROMPT.md", "r") as f:
    SYSTEM_PROMPT = f.read()

all_tools = [
    AgentTools.get_comments,
    AgentTools.get_media_insights,
    AgentTools.get_threads_media_insights,
    AgentTools.list_recent_media,
    AgentTools.reply_to_comment
]

@wrap_model_call
def extend_system_prompt_config(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    influencer_name = request.state.get("influencer_name")

    personality = shared_memory_store.get(("content_production", influencer_name), "personality")
    backstory = shared_memory_store.get(("content_production", influencer_name), "backstory")

    persona_note = ""
    if personality and backstory:
        persona_note = f"\n\nIn any of your interactions, stick to the following personality: {personality.value} and {backstory.value}"

    request = request.override(system_prompt=f"{SYSTEM_PROMPT}{persona_note}")
    return handler(request)


response_handling_agent = create_agent(
    model=response_handling_model,
    tools=all_tools,
    system_prompt=SYSTEM_PROMPT,
    middleware=[
        moderate_reply,
        input_guard,
        ToolCallLimitMiddleware(tool_name="reply_to_comment", thread_limit=5),
        extend_system_prompt_config
    ],
    state_schema=EngagementState,
    checkpointer=checkpointer,
)

opik_tracer = OpikTracer()
response_handling_agent = track_langgraph(response_handling_agent, opik_tracer)