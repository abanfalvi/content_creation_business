from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import Literal

DirectorStep = Literal[
    "call_expert_builder_agent",
    "call_script_drafter_agent",
    "edit_prompts_skills",
    "review_expert_profile",
    "human_review",
    "get_lessons_learned",
    "approved",
    "full_flexibility",
]

class MultiAgentState(AgentState):
    """State for the director's multi-agent workflow."""
    active_agent: NotRequired[DirectorStep]
    system_prompt_read: NotRequired[bool]
    book_title: NotRequired[str]
