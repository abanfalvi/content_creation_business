# Agent that writes the text content, generates the image and edits it in Canva

from .mcp import get_canva_mcp
from .tools import SMWriterAgentTools
from ..models import SM_WRITER_MODEL

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

conn = sqlite3.connect("./checkpoints/distribution_checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)

async def build_sm_writer_agent():
    canva_tools = await get_canva_mcp()
    agent = create_agent(
        ChatOpenRouter(model=SM_WRITER_MODEL, temperature=.2),
        tools=[*canva_tools, SMWriterAgentTools.generate_image, SMWriterAgentTools.download_export, SMWriterAgentTools.save_post_text, SMWriterAgentTools.create_folder],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
        middleware=[
            FilesystemFileSearchMiddleware(
                root_path="/data",
                use_ripgrep=True,
            ),
        ]
        )
    return agent


if __name__ == "__main__":
    sm_writer_agent = asyncio.run(build_sm_writer_agent())