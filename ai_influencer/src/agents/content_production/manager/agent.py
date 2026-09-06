# Content Production Manager Agent
# Aim: Coordinate the work in the department
from dotenv import load_dotenv
from opik.integrations.langchain import OpikTracer, track_langgraph

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware

from ....models import CONTENT_PRODUCTION_MANAGER, MIMO_FALLBACK_MODEL
from ..utils import checkpointer
from ..mcp import get_buffer_mcp
from ....memory_store import shared_memory_store
from .state import ManagerState
from .tools import ManagerTools
from .guardrails import STEP_CONFIG, apply_step_config, verify_end, redact_buffer_get_account_output

load_dotenv()

content_manager_model = ChatOpenRouter(
    model=CONTENT_PRODUCTION_MANAGER,
    temperature=0.2,
    max_tokens=2048
)

model_fallback = ModelFallbackMiddleware(
    ChatOpenRouter(model=MIMO_FALLBACK_MODEL),
)

with open(r"src\agents\content_production\SYSTEM_PROMPT.md", "r") as f:
    SYSTEM_PROMPT = f.read()


async def build_content_manager_agent():
    buffer_tools = await get_buffer_mcp()
    STEP_CONFIG["content_creation"]["tools"] = [
        ManagerTools.call_content_strategist_agent,
        ManagerTools.call_sm_content_writer_agent,
        ManagerTools.read_content_calendar,
        ManagerTools.mark_posted,
        *buffer_tools
    ]
    agent = create_agent(
        model=content_manager_model,
        tools=[
            ManagerTools.call_content_strategist_agent,
            ManagerTools.call_sm_content_writer_agent,
            ManagerTools.read_content_calendar,
            ManagerTools.call_auditor,
            ManagerTools.mark_posted,
            *buffer_tools,
        ],
        system_prompt=SYSTEM_PROMPT,
        state_schema=ManagerState,
        middleware=[apply_step_config, verify_end, model_fallback, redact_buffer_get_account_output],
        checkpointer=checkpointer,
        store=shared_memory_store,
        )
    opik_tracer = OpikTracer()
    agent = track_langgraph(agent, opik_tracer)
    return agent

_content_manager_agent = None

async def get_content_manager_agent():
    global _content_manager_agent
    if _content_manager_agent is None:
        _content_manager_agent = await build_content_manager_agent()
    return _content_manager_agent
