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

from langchain.agents.middleware import ModelFallbackMiddleware
from langgraph.types import Command

from opik.integrations.langchain import OpikTracer, track_langgraph

from .tools import BookSelectionTools
from .prompts import BookSelectionPrompt
from .state import BookSelectionState
from ..models import BOOK_SELECTION_MODEL
from .utils import checkpointer

load_dotenv()

with open("src/agents/content_specialists/prompts/book_selection_agent_prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

opik.configure(workspace="dreadnought0073", project_name="podcast_generation", install_mcp=False)

book_selection_model = ChatOpenRouter(
    model=BOOK_SELECTION_MODEL,
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


# Collect all tools from all step configurations
all_tools = [
    BookSelectionTools.web_search,
    BookSelectionTools.extract_web_content,
    BookSelectionTools.update_booklist,
    BookSelectionTools.read_booklist,
    BookSelectionTools.set_book_to_finish
]

book_selection_agent = create_agent(
    book_selection_model,
    tools=all_tools,
    state_schema=BookSelectionState,
    middleware=[
        ModelFallbackMiddleware(
            ChatOpenRouter(model="nex-agi/nex-n2-mini", temperature=0.2),
            ChatOpenRouter(model="qwen/qwen3.7-flash", temperature=0.2)
        )
    ],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
)

opik_tracer = OpikTracer()
book_selection_agent = track_langgraph(book_selection_agent, opik_tracer)