from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import Literal

ExpertBuilderStep = Literal["retrieve_content", "read_persona", "edit_persona"]

class ExpertBuilderState(AgentState):
    """State for the expert builder agent workflow."""
    current_step: NotRequired[ExpertBuilderStep]
    persona_read: NotRequired[bool]
    book_title: str

# Script drafter agent
ScriptDrafterStep = Literal["edit_script", "read_personas", "retrieve_content"]
