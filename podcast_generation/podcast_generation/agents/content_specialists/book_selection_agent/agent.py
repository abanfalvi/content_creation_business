from pathlib import Path

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent

from langchain.agents.middleware import ModelFallbackMiddleware


from .tools import BookSelectionTools
from .state import BookSelectionState
from ...models import BOOK_SELECTION_MODEL, track
from ..utils import checkpointer


with open(Path(__file__).parent / "prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


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

book_selection_agent = track(book_selection_agent, False)