from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import Literal

# Director agent
DirectorStep = Literal["call_sm_writer_agent", "call_publisher_agent", "review_post", "edit_prompts"]

class MultiAgentState(AgentState):
    """State for the director's multi-agent workflow."""
    active_agent: NotRequired[DirectorStep]