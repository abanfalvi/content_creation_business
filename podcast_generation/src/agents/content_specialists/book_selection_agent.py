import os
from dotenv import load_dotenv
import sqlite3
import opik

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import Callable, List
from langchain_core.utils import secret_from_env, convert_to_secret_str
from langchain_core.messages import ToolMessage

from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse, HumanInTheLoopMiddleware, wrap_tool_call
from langgraph.types import Command

from opik.integrations.langchain import OpikTracer, track_langgraph

from .tools import BookSelectionTools
from .prompts import BookSelectionPrompt
from .state import BookSelectionState

load_dotenv()

with open("src/agents/content_specialists/prompts/book_selection_agent_prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

opik.configure(workspace="dreadnought0073", project_name="podcast_generation")

# Workflow:
# Check if a book name + its PDF source is already available -> If yes, move onto the next step! (make sure data is stored in DB and chunked)
# -> If there is no book name -> find the next source using web search -> add them to the list
# -> If PDF is not available, indicate to the user that it is missing

book_selection_model = ChatOpenRouter(
    model="inclusionai/ling-3.0-flash",
    temperature=0.2,
    # api_key=secret_from_env("OPENROUTER_API_KEY", default=None)
    # api_key=OPENROUTER_API_KEY
)

# Step configuration: maps step name to (prompt, tools, required_state)
STEP_CONFIG = {
    "check_booklist": {
        "prompt": "",
        "tools": [BookSelectionTools.read_booklist],
        "requires": [],
    },
    "find_books": {
        "prompt": BookSelectionPrompt.FIND_BOOKS_PROMPT,
        "tools": [BookSelectionTools.read_booklist, BookSelectionTools.web_search, BookSelectionTools.extract_web_content, BookSelectionTools.update_booklist],
        "requires": [],
    },
    "update_booklist": {
        "prompt": "",
        "tools": [BookSelectionTools.update_booklist],
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
    BookSelectionTools.web_search,
    BookSelectionTools.extract_web_content,
    BookSelectionTools.update_booklist,
    BookSelectionTools.read_booklist,
    BookSelectionTools.set_book_to_finish
]

# Create the agent with step-based configuration
conn = sqlite3.connect("./checkpoints/content_checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)

book_selection_agent = create_agent(
    book_selection_model,
    tools=all_tools,
    state_schema=BookSelectionState,
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
)

opik_tracer = OpikTracer()
book_selection_agent = track_langgraph(book_selection_agent, opik_tracer)