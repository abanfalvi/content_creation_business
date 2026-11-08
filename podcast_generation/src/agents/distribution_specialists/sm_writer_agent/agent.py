# Agent that writes the text content, generates the image and edits it in Canva

from ..mcp import get_canva_mcp
from .tools import SMWriterAgentTools
from ...models import SM_WRITER_MODEL, COMPRESSOR_MODEL, track
from ..utils import checkpointer
from .state import SMWriterState

import asyncio
from langchain.agents import create_agent
from langchain_openrouter import ChatOpenRouter
from langchain.agents.middleware import FilesystemFileSearchMiddleware, SummarizationMiddleware, ModelFallbackMiddleware
from dotenv import load_dotenv
from pathlib import Path


load_dotenv()


with open(Path(__file__).parent / "prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

compressor_model = ChatOpenRouter(
    model=COMPRESSOR_MODEL,
    temperature=0.2,
)

async def build_sm_writer_agent():
    canva_tools = await get_canva_mcp()
    agent = create_agent(
        ChatOpenRouter(model=SM_WRITER_MODEL, temperature=.2),
        tools=[
            *canva_tools, 
            SMWriterAgentTools.generate_image_and_upload_canva,
            SMWriterAgentTools.export_and_download_design,
            SMWriterAgentTools.save_post_text,
            SMWriterAgentTools.create_folder,
            SMWriterAgentTools.load_available_skills,
            SMWriterAgentTools.load_skill_content,
            SMWriterAgentTools.get_script
        ],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
        state_schema=SMWriterState,
        middleware=[
            FilesystemFileSearchMiddleware(
                root_path="data",
                use_ripgrep=True,
            ),
            SummarizationMiddleware(model=compressor_model, trigger=("tokens", 30000), keep=("messages", 8)),
            ModelFallbackMiddleware(
                ChatOpenRouter(model="upstage/solar-pro4", temperature=.2),
                ChatOpenRouter(model="deepseek/deepseek-v4-flash", temperature=.2)
            )
        ]
        )
    agent = track(agent)
    return agent


_sm_writer_agent = None

def get_sm_writer_agent():
    global _sm_writer_agent
    if _sm_writer_agent is None:
        _sm_writer_agent = asyncio.run(build_sm_writer_agent())
    return _sm_writer_agent