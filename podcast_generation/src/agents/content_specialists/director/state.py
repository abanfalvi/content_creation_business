from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import Literal

DirectorStep = Literal["call_book_selection_agent", "call_expert_builder_agent", "call_script_drafter_agent", "edit_prompts", "review_expert_profile", "human_review"]

class MultiAgentState(AgentState):
    """State for the director's multi-agent workflow."""
    active_agent: NotRequired[DirectorStep]
    system_prompt_read: NotRequired[bool]
    book_title: NotRequired[str]

# Book selection agent
BookSelectionStep = Literal["check_booklist", "find_books", "update_booklist"]
