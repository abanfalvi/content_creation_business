# Social Media Content Writer Agent
# Aim: Design the media and text contents to post

from dotenv import load_dotenv
from typing import Any
import opik, os
from opik.integrations.langchain import OpikTracer, track_langgraph

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware

from ....models import SM_CONTENT_WRITER_AGENT
from .tools import AgentTools
from .state import ContentCreatorState
from ...utils import checkpointer
from .guardrails import consistency_check_guardrail, safe_output_guardrail, check_caption_consistency

load_dotenv()

sm_content_writer_model = ChatOpenRouter(
    model=SM_CONTENT_WRITER_AGENT,
    temperature=0.4,
    max_tokens=4096,
    timeout=120000,
    frequency_penalty=0.3
)

opik.configure(workspace="dreadnought0073", project_name="ai_influencer_agency", install_mcp=False)

with open(r"src\agents\content_production\specialists\sm_writer_agent\SYSTEM_PROMPT.md", "r") as f:
    SYSTEM_PROMPT = f.read()

all_tools = [
    AgentTools.load_available_skills,
    AgentTools.append_content,
    AgentTools.edit_captions,
    AgentTools.load_skill_content,
    AgentTools.read_captions,
    AgentTools.read_persona_info,
    AgentTools.generate_audio,
    AgentTools.generate_image,
    AgentTools.generate_video,
    AgentTools.lipsync_video_wth_audio,
    AgentTools.edit_image,
    AgentTools.retrieve_previous_images
]

sm_content_writer_agent = create_agent(
    model=sm_content_writer_model,
    tools=all_tools,
    system_prompt=SYSTEM_PROMPT,
    middleware=[
        safe_output_guardrail,
        consistency_check_guardrail,
        check_caption_consistency,
        SummarizationMiddleware(
            model=ChatOpenRouter(model="inclusionai/ling-3.0-flash"),
            trigger=15000,
        )
    ],
    state_schema=ContentCreatorState,
    checkpointer=checkpointer
)

opik_tracer = OpikTracer()
sm_content_writer_agent = track_langgraph(sm_content_writer_agent, opik_tracer)