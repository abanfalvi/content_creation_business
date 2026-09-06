# Main Orchestrator Agent
# Aim: Main point of contact to get something done for the user

from dotenv import load_dotenv
from typing import Any, Callable
import asyncio
from opik.integrations.langchain import OpikTracer, track_langgraph

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware

from ..models import ORCHESTRATOR, PERSONA_FALLBACK_MODEL_1, PERSONA_FALLBACK_MODEL_2
from .tools import AgentTools
from .state import OrchestratorState
from .utils import get_checkpointer
from ..memory_store import shared_memory_store

load_dotenv()

orchestrator_model = ChatOpenRouter(
    model=ORCHESTRATOR,
    temperature=0.2,
    max_tokens=4096
)

model_fallback = ModelFallbackMiddleware(
    ChatOpenRouter(model=PERSONA_FALLBACK_MODEL_1),
    ChatOpenRouter(model=PERSONA_FALLBACK_MODEL_2),
)

with open(r"src\orchestration\SYSTEM_PROMPT.md", "r") as f:
    SYSTEM_PROMPT = f.read()

all_tools = [
    AgentTools.call_content_production_manager,
    AgentTools.run_persona_creation_workflow,
    AgentTools.submit_persona_review,
    AgentTools.read_persona_info,
    AgentTools.call_response_engagement_agent
]

async def build_orchestrator():
    checkpointer = await get_checkpointer()
    orchestrator_agent = create_agent(
        model=orchestrator_model,
        tools=all_tools,
        system_prompt=SYSTEM_PROMPT,
        middleware=[model_fallback],
        state_schema=OrchestratorState,
        checkpointer=checkpointer,
        store=shared_memory_store,
    )

    opik_tracer = OpikTracer()
    orchestrator_agent = track_langgraph(orchestrator_agent, opik_tracer)

    return orchestrator_agent

orchestrator_agent = None

async def get_orchestrator_agent():
    global orchestrator_agent
    if orchestrator_agent is None:
        orchestrator_agent = await build_orchestrator()
    return orchestrator_agent