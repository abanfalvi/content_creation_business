from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import Literal

BookSelectionStep = Literal["check_booklist", "find_books", "update_booklist"]

class BookSelectionState(AgentState):
    """State for the book selection agent workflow."""
    current_step: NotRequired[BookSelectionStep]

# Expert builder agent
ExpertBuilderStep = Literal["retrieve_content", "read_persona", "edit_persona"]
