# Publishes and then manages the platform

from .tools import PublisherAgentTools
from ..models import PUBLISHER_MODEL
from .mcp import get_buffer_mcp
from .director import checkpointer

import asyncio
import sqlite3
from langchain.agents import create_agent
from langchain_openrouter import ChatOpenRouter
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain.agents.middleware import FilesystemFileSearchMiddleware, HumanInTheLoopMiddleware
from dotenv import load_dotenv

load_dotenv()

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
    return agent


if __name__ == "__main__":
    publisher_agent = asyncio.run(build_publisher_agent())