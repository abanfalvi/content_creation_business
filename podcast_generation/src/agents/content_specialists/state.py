from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import Literal

# Director agent
DirectorStep = Literal["call_book_selection_agent", "call_expert_builder_agent", "call_script_drafter_agent", "edit_prompts", "review_expert_profile", "human_review"]

class MultiAgentState(AgentState):
    """State for the director's multi-agent workflow."""
    active_agent: NotRequired[DirectorStep]

# Book selection agent
BookSelectionStep = Literal["check_booklist", "find_books", "update_booklist"]

class BookSelectionState(AgentState):
    """State for the book selection agent workflow."""
    current_step: NotRequired[BookSelectionStep]

# Expert builder agent
ExpertBuilderStep = Literal["retrieve_content", "read_persona", "edit_persona"]

class ExpertBuilderState(AgentState):
    """State for the expert builder agent workflow."""
    current_step: NotRequired[ExpertBuilderStep]
    persona_read: NotRequired[bool]

# Script drafter agent
ScriptDrafterStep = Literal["edit_script", "read_personas", "retrieve_content"]

class ScriptDrafterState(AgentState):
    """State for the script drafter agent workflow."""
    current_step: NotRequired[ScriptDrafterStep]
    script_read: NotRequired[bool]

