# Backstory Agent
# Aim: Design the interests, relationships and life narratives for the influencer

from dotenv import load_dotenv
from typing import Any
import os
from opik.integrations.langchain import OpikTracer, track_langgraph

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langchain.agents.middleware import dynamic_prompt, ToolErrorMiddleware, ModelFallbackMiddleware
from langchain.agents.middleware.types import ModelRequest, ToolCallRequest

from .....models import BACKSTORY_AGENT, PERSONA_FALLBACK_MODEL_1, PERSONA_FALLBACK_MODEL_2
from .tools import AgentTools
from .state import BackstoryState
from ...utils import checkpointer, on_tool_error, verify_artifact, render_available_skills
from .....memory_store import shared_memory_store

load_dotenv()

backstory_model = ChatOpenRouter(
    model=BACKSTORY_AGENT,
    temperature=0.4,
    max_tokens=4096,
    frequency_penalty=0.3
)

model_fallback = ModelFallbackMiddleware(
    ChatOpenRouter(model=PERSONA_FALLBACK_MODEL_1),
    ChatOpenRouter(model=PERSONA_FALLBACK_MODEL_2),
)

with open(r"src\agents\persona_identity\specialists\backstory_agent\SYSTEM_PROMPT.md", "r") as f:
    SYSTEM_PROMPT = f.read()

SKILLS_PATH = r"src\agents\persona_identity\specialists\backstory_agent\skills"

@dynamic_prompt
def inject_character_design(request: ModelRequest) -> str:
    prompt = SYSTEM_PROMPT

    skills = render_available_skills(SKILLS_PATH)
    if skills:
        prompt = f"{prompt}\n\n---\n\nThe following skills from past runs are available to guide your work:\n\n{skills}"

    influencer_name = request.state.get("influencer_name")
    if not influencer_name:
        return prompt
    path = f"src/influencers/{influencer_name}/CHARACTER.md"
    if not os.path.exists(path):
        return prompt
    with open(path, "r", encoding="utf-8") as f:
        character = f.read()
    return f"{prompt}\n\n---\n\nThe following character has already been designed. Keep personality and voice choices consistent with it:\n\n{character}"

all_tools = [
    AgentTools.append_content,
    AgentTools.read_influencer_backstory,
    AgentTools.edit_influencer_backstory,
    AgentTools.check_existing_influencers,
]

backstory_agent = create_agent(
    model=backstory_model,
    tools=all_tools,
    system_prompt=SYSTEM_PROMPT,
    middleware=[
        inject_character_design,
        ToolErrorMiddleware(on_error=on_tool_error, tools=["append_content", "edit_influencer_backstory"]),
        model_fallback,
        verify_artifact,
    ],
    state_schema=BackstoryState,
    checkpointer=checkpointer,
    store=shared_memory_store,
)

opik_tracer = OpikTracer()
backstory_agent = track_langgraph(backstory_agent, opik_tracer)