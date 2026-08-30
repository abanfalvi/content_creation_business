# Character Design Agent
# Aim: Design the body and face of the character and their general visual identity

from dotenv import load_dotenv
import opik
from opik.integrations.langchain import OpikTracer, track_langgraph

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent

from langchain.agents.middleware import ModelFallbackMiddleware

from .....models import CHARACTER_DESIGN_AGENT
from .tools import AgentTools
from .state import CharacterState
from ...utils import checkpointer

load_dotenv()

character_design_model = ChatOpenRouter(
    model=CHARACTER_DESIGN_AGENT,
    temperature=0.5,
    max_tokens=8192
)

opik.configure(workspace="dreadnought0073", project_name="ai_influencer_agency", install_mcp=False)


with open(r"src\agents\persona_identity\specialists\character_design_agent\SYSTEM_PROMPT.md", "r") as f:
    SYSTEM_PROMPT = f.read()

all_tools = [
    AgentTools.load_available_skills,
    AgentTools.append_content,
    AgentTools.create_influencer_files,
    AgentTools.edit_character_design,
    AgentTools.load_skill_content,
    AgentTools.read_character_design
]

# If the agent finishes without fulfilling the proper criteria: add rubric score
character_design_agent = create_agent(
    model=character_design_model,
    tools=all_tools,
    system_prompt=SYSTEM_PROMPT,
    middleware=[],
    state_schema=CharacterState,
    checkpointer=checkpointer
)

opik_tracer = OpikTracer()
character_design_agent = track_langgraph(character_design_agent, opik_tracer)