# Main Orchestrator Agent
# Aim: Main point of contact to get something done for the user

from dotenv import load_dotenv
from typing import Any, Callable
import opik, os
from opik.integrations.langchain import OpikTracer, track_langgraph

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent

from ..models import ORCHESTRATOR
from .tools import AgentTools
from .state import OrchestratorState

load_dotenv()

orchestrator_model = ChatOpenRouter(
    model=ORCHESTRATOR,
    temperature=0.2,
    max_tokens=4096
)

opik.configure(workspace="dreadnought0073", project_name="ai_influencer_agency", install_mcp=False)

with open(r"src\orchestration\SYSTEM_PROMPT.md", "r") as f:
    SYSTEM_PROMPT = f.read()

all_tools = [
    AgentTools.call_content_production_manager,
    AgentTools.run_persona_creation_workflow
]

orchestrator_agent = create_agent(
    model=orchestrator_model,
    tools=all_tools,
    system_prompt=SYSTEM_PROMPT,
    state_schema=OrchestratorState,
)

opik_tracer = OpikTracer()
orchestrator_agent = track_langgraph(orchestrator_agent, opik_tracer)