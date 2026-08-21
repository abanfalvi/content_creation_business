# Agent that writes the text content, generates the image and edits it in Canva

from .mcp import get_canva_mcp
from .tools import SMWriterAgentTools
from ..models import SM_WRITER_MODEL, COMPRESSOR_MODEL
from .utils import checkpointer
from .state import SMWriterState

import asyncio
import opik
from langchain.agents import create_agent
from langchain_openrouter import ChatOpenRouter
from langchain.agents.middleware import FilesystemFileSearchMiddleware, HumanInTheLoopMiddleware, SummarizationMiddleware, ModelFallbackMiddleware
from dotenv import load_dotenv

from opik.integrations.langchain import OpikTracer, track_langgraph

load_dotenv()

opik.configure(workspace="dreadnought0073", project_name="podcast_generation", install_mcp=False)

with open("src/agents/distribution_specialists/prompts/sm_writer_agent_prompt.md", "r", encoding="utf-8") as f:
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
            SummarizationMiddleware(model=compressor_model, trigger=("tokens", 20000), keep=("messages", 8)),
            ModelFallbackMiddleware(
                ChatOpenRouter(model="upstage/solar-pro4", temperature=.2),
                ChatOpenRouter(model="deepseek/deepseek-v4-flash", temperature=.2)
            )
        ]
        )
    opik_tracer = OpikTracer()
    agent = track_langgraph(agent, opik_tracer)
    return agent


_sm_writer_agent = None

def get_sm_writer_agent():
    global _sm_writer_agent
    if _sm_writer_agent is None:
        _sm_writer_agent = asyncio.run(build_sm_writer_agent())
    return _sm_writer_agent