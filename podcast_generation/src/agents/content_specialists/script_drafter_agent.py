from dotenv import load_dotenv
import opik

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent

from langchain.agents.middleware import SummarizationMiddleware, FilesystemFileSearchMiddleware, ModelFallbackMiddleware

from opik.integrations.langchain import OpikTracer, track_langgraph

from .tools import ScriptDrafterTools, ExpertProfileTools
from .state import ScriptDrafterState
from ..models import SCRIPT_DRAFTER_MODEL, COMPRESSOR_MODEL
from .utils import checkpointer

load_dotenv()

opik.configure(workspace="dreadnought0073", project_name="podcast_generation", install_mcp=False)

with open("src/agents/content_specialists/prompts/script_drafter_agent_prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

script_drafter_model = ChatOpenRouter(
    model=SCRIPT_DRAFTER_MODEL,
    temperature=0.3,
)

compressor_model = ChatOpenRouter(
    model=COMPRESSOR_MODEL,
    temperature=0.2,
)


# Collect all tools from all step configurations
all_tools = [
    ScriptDrafterTools.append_script,
    ScriptDrafterTools.edit_script,
    ScriptDrafterTools.read_script,
    ScriptDrafterTools.read_personas,
    ExpertProfileTools.retrieve_info,
    ScriptDrafterTools.read_book_content,
    ScriptDrafterTools.load_available_skills,
    ScriptDrafterTools.load_skill_content
]

script_drafter_agent = create_agent(
    script_drafter_model,
    tools=all_tools,
    state_schema=ScriptDrafterState,
    system_prompt=SYSTEM_PROMPT,
    middleware=[
        FilesystemFileSearchMiddleware(
            root_path="data",
            use_ripgrep=True,
        ),
        SummarizationMiddleware(model=compressor_model, trigger=("tokens", 30000), keep=("messages", 5)),
        ModelFallbackMiddleware(
            ChatOpenRouter(model="upstage/solar-pro4", temperature=0.3),
            ChatOpenRouter(model="deepseek/deepseek-v4-flash", temperature=0.3)
        )
    ],
    checkpointer=checkpointer,
)

opik_tracer = OpikTracer()
script_drafter_agent = track_langgraph(script_drafter_agent, opik_tracer)