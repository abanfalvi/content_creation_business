from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import Literal

ScriptPlannerStep = Literal["edit_script", "read_personas", "retrieve_content"]

class ScriptPlannerState(AgentState):
    """State for the script drafter agent workflow."""
    current_step: NotRequired[ScriptPlannerStep]
    script_read: NotRequired[bool]
    book_title: str
    verify_attempts: NotRequired[int]
