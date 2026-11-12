from pathlib import Path

from langchain.agents import create_agent
from langchain_openrouter import ChatOpenRouter

from .tools import LessonsLearnedExtracterAgentTools
from .state import LLExtractorState
from ...models import LL_EXTRACTOR_AGENT


with open(Path(__file__).parent / "prompt.md", "r", encoding="utf-8") as f:
    PROMPT_TEMPLATE = f.read()


def build_lessons_learned_extractor_agent(store):
    "The extractor needs the run's store, so it is built per call instead of once at import."
    return create_agent(
        model=ChatOpenRouter(model=LL_EXTRACTOR_AGENT, temperature=.2),
        tools=[LessonsLearnedExtracterAgentTools.save_learnable_traces],
        state_schema=LLExtractorState,
        store=store
    )


def build_extraction_request(traces) -> str:
    return PROMPT_TEMPLATE.format(traces=traces)
