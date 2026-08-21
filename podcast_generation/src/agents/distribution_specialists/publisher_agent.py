# Publishes and then manages the platform

from .tools import PublisherAgentTools
from ..models import PUBLISHER_MODEL
from .mcp import get_buffer_mcp
from .utils import checkpointer

import asyncio
import opik
from langchain.agents import create_agent
from langchain_openrouter import ChatOpenRouter
from dotenv import load_dotenv

from opik.integrations.langchain import OpikTracer, track_langgraph

load_dotenv()

opik.configure(workspace="dreadnought0073", project_name="podcast_generation", install_mcp=False)

with open("src/agents/distribution_specialists/prompts/sm_writer_agent_prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

async def build_publisher_agent():
    sm_management_tools = await get_buffer_mcp()
    agent = create_agent(
        ChatOpenRouter(model=PUBLISHER_MODEL, temperature=.2),
        tools=[
            PublisherAgentTools.search_show,
            PublisherAgentTools.search_episode,
            PublisherAgentTools.get_show_info,
            PublisherAgentTools.get_show_episodes,
            PublisherAgentTools.get_episode_details,
            PublisherAgentTools.load_available_skills,
            PublisherAgentTools.load_skill_content,
            # *sm_management_tools,
        ],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
        )
    opik_tracer = OpikTracer()
    agent = track_langgraph(agent, opik_tracer)
    return agent


_publisher_agent = None

def get_publisher_agent():
    global _publisher_agent
    if _publisher_agent is None:
        _publisher_agent = asyncio.run(build_publisher_agent())
    return _publisher_agent