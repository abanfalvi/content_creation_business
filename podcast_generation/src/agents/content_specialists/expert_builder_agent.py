# Workflow: 
# Iteratively query the database while developing an expert persona

import os
from dotenv import load_dotenv
import sqlite3
import opik

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import Callable, List
from langchain_core.messages import ToolMessage

from langchain.agents.middleware import wrap_model_call, ModelRequest, FilesystemFileSearchMiddleware, SummarizationMiddleware, ModelFallbackMiddleware
from langgraph.types import Command

from opik.integrations.langchain import OpikTracer, track_langgraph

from .tools import ExpertProfileTools
from .state import ExpertBuilderState
from ..models import EXPERT_BUILDER_MODEL, COMPRESSOR_MODEL
from .utils import checkpointer

load_dotenv()

opik.configure(workspace="dreadnought0073", project_name="podcast_generation", install_mcp=False)

with open("src/agents/content_specialists/prompts/expert_builder_agent_prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

expert_builder_model = ChatOpenRouter(
    model=EXPERT_BUILDER_MODEL,
    temperature=0.2,
    # api_key=secret_from_env("OPENROUTER_API_KEY", default=None)
    # api_key=OPENROUTER_API_KEY
)

compressor_model = ChatOpenRouter(
    model=COMPRESSOR_MODEL,
    temperature=0.2,
)

STEP_CONFIG = {
    "retrieve_content": {
        "prompt": "",
        "tools": [],
        "requires": [],
    },
    "read_persona": {
        "prompt": "",
        "tools": [],
        "requires": [],
    },
    "edit_persona": {
        "prompt": "",
        "tools": [],
        "requires": [], 
    },
}


# Collect all tools from all step configurations
all_tools = [
    ExpertProfileTools.edit_persona,
    ExpertProfileTools.read_persona,
    ExpertProfileTools.retrieve_info,
    ExpertProfileTools.append_persona,
    ExpertProfileTools.read_book_content,
    ExpertProfileTools.load_skill_content,
    ExpertProfileTools.load_available_skills
]

expert_builder_agent = create_agent(
    expert_builder_model,
    tools=all_tools,
    state_schema=ExpertBuilderState,
    system_prompt=SYSTEM_PROMPT,
    middleware=[
        FilesystemFileSearchMiddleware(
            root_path="data",
            use_ripgrep=True,
        ),
        SummarizationMiddleware(model=compressor_model, trigger=("tokens", 20000), keep=("messages", 5)),
        ModelFallbackMiddleware(
            ChatOpenRouter(model="upstage/solar-pro4", temperature=0.2),
            ChatOpenRouter(model="deepseek/deepseek-v4-flash", temperature=0.2)
        )
    ],
    checkpointer=checkpointer,
)

opik_tracer = OpikTracer()
expert_builder_agent = track_langgraph(expert_builder_agent, opik_tracer)