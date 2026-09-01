# Content Strategist Agent
# Aim: Design the content calendar to follow

from dotenv import load_dotenv
from typing import Any, Callable
from opik.integrations.langchain import OpikTracer, track_langgraph

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain.agents.middleware.types import ModelRequest, ModelResponse

from ..models import AUDITOR_MODEL
from .tools import AgentTools
from .state import AuditorState
from ..memory_store import shared_memory_store

load_dotenv()

auditor_model = ChatOpenRouter(
    model=AUDITOR_MODEL,
    temperature=0.2,
    max_tokens=4096
)

with open(r"src\auditor\SYSTEM_PROMPT.md", "r") as f:
    SYSTEM_PROMPT = f.read()

all_tools = [
    # AgentTools.read_task_board,
    AgentTools.save_learnable_traces,
    AgentTools.call_skill_converter,
    AgentTools.read_existing_skills,
    # AgentTools.update_task_board,
]

STEP_CONFIG = {
    "save_traces": {
        "prompt": "",
        "tools": [AgentTools.save_learnable_traces, AgentTools.read_existing_skills]
    },
    "convert_to_skill": {
        "prompt": "In this step, call the skill converter model to convert your creates reinforcing traces into skills for the agents.",
        "tools": [AgentTools.call_skill_converter]
    }
}

@wrap_model_call
def apply_step_config(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """Configure agent behavior based on the current step."""
    active_agent = request.state.get("active_step", "save_traces")
    
    # Look up step configuration
    stage_config = STEP_CONFIG[active_agent]

    step_prompt = stage_config["prompt"].format(
        **request.state
        )

    # Inject system prompt and step-specific tools
    if step_prompt:
        request = request.override(
            system_prompt=f"{SYSTEM_PROMPT} \n\n {step_prompt}",
            tools=stage_config["tools"],
        )
    else:
        request = request.override(
            tools=stage_config["tools"],
        )

    return handler(request)

auditor_agent = create_agent(
    model=auditor_model,
    tools=all_tools,
    system_prompt=SYSTEM_PROMPT,
    state_schema=AuditorState,
    store=shared_memory_store
)

opik_tracer = OpikTracer()
auditor_agent = track_langgraph(auditor_agent, opik_tracer)