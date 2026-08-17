# Write the script while iterating over the DB + using the created expert persona + host

from dotenv import load_dotenv
import sqlite3
import opik

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import Callable, List
from langchain_core.messages import ToolMessage

from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse, HumanInTheLoopMiddleware, SummarizationMiddleware, FilesystemFileSearchMiddleware

from opik.integrations.langchain import OpikTracer, track_langgraph

from .tools import ScriptDrafterTools, ExpertProfileTools
from .state import ScriptDrafterState
from ..models import SCRIPT_DRAFTER_MODEL, COMPRESSOR_MODEL
from .director import checkpointer

load_dotenv()

opik.configure(workspace="dreadnought0073", project_name="podcast_generation")

with open("src/agents/content_specialists/prompts/script_drafter_agent_prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

script_drafter_model = ChatOpenRouter(
    model=SCRIPT_DRAFTER_MODEL,
    temperature=0.3,
    # api_key=secret_from_env("OPENROUTER_API_KEY", default=None)
    # api_key=OPENROUTER_API_KEY
)

compressor_model = ChatOpenRouter(
    model=COMPRESSOR_MODEL,
    temperature=0.2,
)

# Step configuration: maps step name to (prompt, tools, required_state)
STEP_CONFIG = {
    "edit_script": {
        "prompt": "",
        "tools": [],
        "requires": [],
    },
    "read_personas": {
        "prompt": "",
        "tools": [],
        "requires": [],
    },
    "retrieve_content": {
        "prompt": "",
        "tools": [],
        "requires": [], # these go into the prompt
    },
}

@wrap_model_call
def apply_step_config(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """Configure agent behavior based on the current step."""
    # Get current step (defaults to check_booklist for first interaction)
    current_step = request.state.get("current_step", "check_booklist")

    # Look up step configuration
    stage_config = STEP_CONFIG[current_step]

    # Validate required state exists
    for key in stage_config["requires"]:
        if request.state.get(key) is None:
            raise ValueError(f"{key} must be set before reaching {current_step}")

    # Format prompt with state values (supports {warranty_status}, {issue_type}, etc.)
    step_prompt = stage_config["prompt"].format(
        **request.state
        )

    # Inject system prompt and step-specific tools
    request = request.override(
        system_prompt=f"{SYSTEM_PROMPT}\n\n{step_prompt}".strip(),
        tools=stage_config["tools"],
    )

    return handler(request)


# Collect all tools from all step configurations
all_tools = [
    ScriptDrafterTools.append_script,
    ScriptDrafterTools.edit_script,
    ScriptDrafterTools.read_script,
    ScriptDrafterTools.read_personas,
    ExpertProfileTools.retrieve_info,
]

script_drafter_agent = create_agent(
    script_drafter_model,
    tools=all_tools,
    state_schema=ScriptDrafterState,
    system_prompt=SYSTEM_PROMPT,
    middleware=[
        FilesystemFileSearchMiddleware(
            root_path="/data",
            use_ripgrep=True,
        ),
        SummarizationMiddleware(model=compressor_model, trigger=("tokens", 20000), keep=("messages", 8)),
    ],
    checkpointer=checkpointer,
)

opik_tracer = OpikTracer()
script_drafter_agent = track_langgraph(script_drafter_agent, opik_tracer)