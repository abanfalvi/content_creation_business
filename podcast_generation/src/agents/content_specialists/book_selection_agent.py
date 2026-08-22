from dotenv import load_dotenv
import opik

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent

from langchain.agents.middleware import ModelFallbackMiddleware

from opik.integrations.langchain import OpikTracer, track_langgraph

from .tools import BookSelectionTools
from .prompts import BookSelectionPrompt
from .state import BookSelectionState
from ..models import BOOK_SELECTION_MODEL
from .utils import checkpointer

load_dotenv()

with open("src/agents/content_specialists/prompts/book_selection_agent_prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

opik.configure(workspace="dreadnought0073", project_name="podcast_generation", install_mcp=False)

book_selection_model = ChatOpenRouter(
    model=BOOK_SELECTION_MODEL,
    temperature=0.2,
)


# Collect all tools from all step configurations
all_tools = [
    BookSelectionTools.web_search,
    BookSelectionTools.extract_web_content,
    BookSelectionTools.update_booklist,
    BookSelectionTools.read_booklist,
    BookSelectionTools.set_book_to_finish,
    BookSelectionTools.add_filepath
]

book_selection_agent = create_agent(
    book_selection_model,
    tools=all_tools,
    state_schema=BookSelectionState,
    middleware=[
        ModelFallbackMiddleware(
            ChatOpenRouter(model="nex-agi/nex-n2-mini", temperature=0.2),
            ChatOpenRouter(model="qwen/qwen3.7-flash", temperature=0.2)
        )
    ],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
)

opik_tracer = OpikTracer()
book_selection_agent = track_langgraph(book_selection_agent, opik_tracer)