# Content Strategist Agent
# Aim: Design the content calendar to follow

from dotenv import load_dotenv
from typing import Any, Callable
import opik, os
from opik.integrations.langchain import OpikTracer, track_langgraph

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent

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

opik.configure(workspace="dreadnought0073", project_name="ai_influencer_agency", install_mcp=False)

with open(r"src\auditor\SYSTEM_PROMPT.md", "r") as f:
    SYSTEM_PROMPT = f.read()

all_tools = [
    # AgentTools.read_task_board,
    AgentTools.save_learnable_traces,
    # AgentTools.update_task_board,
]

auditor_agent = create_agent(
    model=auditor_model,
    tools=all_tools,
    system_prompt=SYSTEM_PROMPT,
    state_schema=AuditorState,
    store=shared_memory_store
)

opik_tracer = OpikTracer()
auditor_agent = track_langgraph(auditor_agent, opik_tracer)