# Publishes and then manages the platform

from .tools import PublisherAgentTools
from ...models import PUBLISHER_MODEL, track
from ..mcp import get_buffer_mcp
from ..utils import get_checkpointer

import asyncio
from langchain.agents import create_agent
from langchain_openrouter import ChatOpenRouter
from pathlib import Path




with open(Path(__file__).parent / "prompt.md", "r", encoding="utf-8") as f:
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
        checkpointer=get_checkpointer(),
        )
    agent = track(agent)
    return agent


_publisher_agent = None

def get_publisher_agent():
    global _publisher_agent
    if _publisher_agent is None:
        _publisher_agent = asyncio.run(build_publisher_agent())
    return _publisher_agent