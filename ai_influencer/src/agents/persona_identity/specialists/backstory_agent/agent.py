# Backstory Agent
# Aim: Design the interests, relationships and life narratives for the influencer

from dotenv import load_dotenv
from typing import Any
import opik, os
from opik.integrations.langchain import OpikTracer, track_langgraph

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langchain.agents.middleware import dynamic_prompt
from langchain.agents.middleware.types import ModelRequest

from .....models import BACKSTORY_AGENT
from .tools import AgentTools
from .state import BackstoryState
from ...utils import checkpointer

load_dotenv()

backstory_model = ChatOpenRouter(
    model=BACKSTORY_AGENT,
    temperature=0.5,
    max_tokens=8192
)

opik.configure(workspace="dreadnought0073", project_name="ai_influencer_agency", install_mcp=False)

@dynamic_prompt
def inject_character_design(request: ModelRequest) -> str:
    influencer_name = request.state.get("influencer_name")
    if not influencer_name:
        return SYSTEM_PROMPT
    path = f"src/influencers/{influencer_name}/CHARACTER.md"
    if not os.path.exists(path):
        return SYSTEM_PROMPT
    with open(path, "r", encoding="utf-8") as f:
        character = f.read()
    return f"{SYSTEM_PROMPT}\n\n---\n\nThe following character has already been designed. Keep personality and voice choices consistent with it:\n\n{character}"


with open(r"src\agents\persona_identity\specialists\backstory_agent\SYSTEM_PROMPT.md", "r") as f:
    SYSTEM_PROMPT = f.read()

all_tools = [
    AgentTools.load_available_skills,
    AgentTools.append_content,
    AgentTools.read_influencer_backstory,
    AgentTools.load_skill_content,
    AgentTools.edit_influencer_backstory,
]

backstory_agent = create_agent(
    model=backstory_model,
    tools=all_tools,
    system_prompt=SYSTEM_PROMPT,
    middleware=[inject_character_design],
    state_schema=BackstoryState,
    checkpointer=checkpointer
)

opik_tracer = OpikTracer()
backstory_agent = track_langgraph(backstory_agent, opik_tracer)