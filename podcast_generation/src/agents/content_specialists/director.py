
import sqlite3

from langchain.agents import create_agent
from langchain.agents import AgentState
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse, HumanInTheLoopMiddleware, wrap_tool_call
from langgraph.graph import StateGraph, START, END

from typing import Literal, Callable
from typing_extensions import NotRequired

from .director_tools import DirectorTools
from .prompts import ContentDirectorPrompt
from .state import MultiAgentState, DirectorStep

with open("src/agents/content_specialists/prompts/director_agent_prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

# Step configuration: maps step name to (prompt, tools, required_state)
STEP_CONFIG = {
    "call_book_selection_agent": {
        "prompt": "",
        "tools": [DirectorTools.call_book_selection_agent],
        "requires": [],
    },
    "call_expert_builder_agent": {
        "prompt": "",
        "tools": [DirectorTools.call_expert_builder_agent],
        "requires": [],
    },
    "call_script_drafter_agent": {
        "prompt": "",
        "tools": [DirectorTools.call_script_drafter_agent],
        "requires": [],
    },
    # set current step/ active agent to this, when needed, during invoke method
    "edit_prompts": {
        "prompt": "",
        "tools": [DirectorTools.edit_subagents_system_prompt, DirectorTools.read_subagents_system_prompt],
        "requires": [],
    },
    "review_expert_profile": {
        "prompt": ContentDirectorPrompt.REVIEW_EXPERT_PROFILE,
        "tools": [DirectorTools.call_expert_builder_agent, DirectorTools.call_script_drafter_agent],
        "requires": [],
    },

}

@wrap_model_call
def apply_step_config(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """Configure agent behavior based on the current step."""
    active_agent = request.state.get("active_agent", "call_book_selection_agent")

    # Look up step configuration
    stage_config = STEP_CONFIG[active_agent]

    # Validate required state exists
    for key in stage_config["requires"]:
        if request.state.get(key) is None:
            raise ValueError(f"{key} must be set before reaching {active_agent}")

    step_prompt = stage_config["prompt"].format(
        **request.state
        )

    # Inject system prompt and step-specific tools
    if step_prompt:
        request = request.override(
            system_prompt=f"{SYSTEM_PROMPT}\n\n{step_prompt}".strip(),
            tools=stage_config["tools"],
        )
    else:
        request = request.override(
            # system_prompt=f"{SYSTEM_PROMPT}\n\n{step_prompt}".strip(),
            tools=stage_config["tools"],
        )

    return handler(request)

all_tools = [
    DirectorTools.call_book_selection_agent,
    DirectorTools.call_expert_builder_agent,
    DirectorTools.call_script_drafter_agent,
    DirectorTools.read_subagents_system_prompt,
    DirectorTools.edit_subagents_system_prompt
]

conn = sqlite3.connect("./checkpoints/content_checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)

director_agent = create_agent(
    model="deepseek/deepseek-v4-flash",
    tools=all_tools,
    system_prompt=SYSTEM_PROMPT,
    state_schema=MultiAgentState,
    middleware=[apply_step_config],
    checkpointer=checkpointer
)
