# Character Design Agent
# Aim: Design the body and face of the character and their general visual identity

from dotenv import load_dotenv
from opik.integrations.langchain import OpikTracer, track_langgraph

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langchain.agents.middleware import ToolErrorMiddleware, ModelFallbackMiddleware, dynamic_prompt
from langchain.agents.middleware.types import ModelRequest

from .....models import CHARACTER_DESIGN_AGENT, PERSONA_FALLBACK_MODEL_1, PERSONA_FALLBACK_MODEL_2
from .tools import AgentTools
from .state import CharacterState
from ...utils import checkpointer, on_tool_error, verify_artifact, render_available_skills
from .....memory_store import shared_memory_store

load_dotenv()

character_design_model = ChatOpenRouter(
    model=CHARACTER_DESIGN_AGENT,
    temperature=0.4,
    max_tokens=4096,
    frequency_penalty=0.3
)

model_fallback = ModelFallbackMiddleware(
    ChatOpenRouter(model=PERSONA_FALLBACK_MODEL_1),
    ChatOpenRouter(model=PERSONA_FALLBACK_MODEL_2),
)


with open(r"src\agents\persona_identity\specialists\character_design_agent\SYSTEM_PROMPT.md", "r") as f:
    SYSTEM_PROMPT = f.read()

SKILLS_PATH = r"src\agents\persona_identity\specialists\character_design_agent\skills"

@dynamic_prompt
def inject_available_skills(request: ModelRequest) -> str:
    skills = render_available_skills(SKILLS_PATH)
    if not skills:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n\n---\n\nThe following skills from past runs are available to guide your work:\n\n{skills}"

all_tools = [
    AgentTools.append_content,
    AgentTools.create_influencer_files,
    AgentTools.edit_character_design,
    AgentTools.read_character_design,
    AgentTools.check_existing_influencers,
]

# If the agent finishes without fulfilling the proper criteria: add rubric score
character_design_agent = create_agent(
    model=character_design_model,
    tools=all_tools,
    system_prompt=SYSTEM_PROMPT,
    middleware=[inject_available_skills, ToolErrorMiddleware(on_error=on_tool_error, tools=["append_content", "edit_character_design"]), model_fallback, verify_artifact],
    state_schema=CharacterState,
    checkpointer=checkpointer,
    store=shared_memory_store,
)

opik_tracer = OpikTracer()
character_design_agent = track_langgraph(character_design_agent, opik_tracer)