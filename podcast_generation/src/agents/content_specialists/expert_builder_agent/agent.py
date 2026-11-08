from dotenv import load_dotenv
from pathlib import Path

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent

from langchain.agents.middleware import FilesystemFileSearchMiddleware, SummarizationMiddleware, ModelFallbackMiddleware


from .tools import ExpertProfileTools
from ..shared_tools import SharedContentTools
from .state import ExpertBuilderState
from ...models import EXPERT_BUILDER_MODEL, COMPRESSOR_MODEL, track
from ..utils import checkpointer

load_dotenv()


with open(Path(__file__).parent / "prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

expert_builder_model = ChatOpenRouter(
    model=EXPERT_BUILDER_MODEL,
    temperature=0.2,
)

compressor_model = ChatOpenRouter(
    model=COMPRESSOR_MODEL,
    temperature=0.2,
)


# Collect all tools from all step configurations
all_tools = [
    ExpertProfileTools.edit_persona,
    ExpertProfileTools.read_persona,
    SharedContentTools.retrieve_info,
    ExpertProfileTools.append_persona,
    ExpertProfileTools.read_book_content,
    ExpertProfileTools.load_skill_content,
    ExpertProfileTools.load_available_skills,
]

expert_builder_agent = create_agent(
    expert_builder_model,
    tools=all_tools,
    state_schema=ExpertBuilderState,
    system_prompt=SYSTEM_PROMPT,
    middleware=[
        FilesystemFileSearchMiddleware(
            root_path="data",
            use_ripgrep=True,
        ),
        SummarizationMiddleware(model=compressor_model, trigger=("tokens", 30000), keep=("messages", 5)),
        ModelFallbackMiddleware(
            ChatOpenRouter(model="upstage/solar-pro4", temperature=0.2),
            ChatOpenRouter(model="deepseek/deepseek-v4-flash", temperature=0.2)
        )
    ],
    checkpointer=checkpointer,
)

expert_builder_agent = track(expert_builder_agent)