# Content Strategist Agent
# Aim: Design the content calendar to follow

from dotenv import load_dotenv
from typing import Any, Callable
from opik.integrations.langchain import OpikTracer, track_langgraph

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain.agents.middleware.types import ModelRequest, ModelResponse

from .....models import CONTENT_CALENDAR_AGENT
from .tools import AgentTools
from .state import ContentPlanningState
from ...utils import checkpointer
from .....memory_store import shared_memory_store

load_dotenv()

content_strategist_model = ChatOpenRouter(
    model=CONTENT_CALENDAR_AGENT,
    temperature=0.5,
    max_tokens=4096
)

with open(r"src\agents\content_production\specialists\content_strategist_agent\SYSTEM_PROMPT.md", "r") as f:
    SYSTEM_PROMPT = f.read()

all_tools = [
    AgentTools.add_calendar_entry,
    AgentTools.edit_calendar_entry,
    AgentTools.list_upcoming_contents,
    AgentTools.read_persona_info,
    AgentTools.get_current_date,
    AgentTools.save_influencer_journey,
    AgentTools.load_influencer_journey,
    AgentTools.content_strategy
]

STEP_CONFIG = {
    "calendar_creation_step": {
        "prompt": "",
        "tools": [tool for tool in all_tools if tool.name != "review_content_calendar"]
    },
    "review_step": {
        "prompt": "Send your proposed content calendar to the reviewer for final approval",
        "tools": []
    }
}

@wrap_model_call
def apply_step_config(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """Configure agent behavior based on the current step."""
    active_agent = request.state.get("active_step", "calendar_creation_step")
    
    # Look up step configuration
    stage_config = STEP_CONFIG[active_agent]

    step_prompt = stage_config["prompt"].format(
        **request.state
        )

    # Inject system prompt and step-specific tools
    if step_prompt:
        request = request.override(
            system_prompt=step_prompt,
            tools=stage_config["tools"],
        )
    else:
        request = request.override(
            tools=stage_config["tools"],
        )

    return handler(request)

content_strategist_agent = create_agent(
    model=content_strategist_model,
    tools=all_tools,
    system_prompt=SYSTEM_PROMPT,
    middleware=[],
    state_schema=ContentPlanningState,
    checkpointer=checkpointer,
    store=shared_memory_store
)

opik_tracer = OpikTracer()
content_strategist_agent = track_langgraph(content_strategist_agent, opik_tracer)