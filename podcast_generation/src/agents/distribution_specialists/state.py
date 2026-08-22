from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import Literal

# Director agent
DirectorStep = Literal["call_sm_writer_agent", "call_publisher_agent", "review_post", "edit_prompts", "get_lessons_learned"]

class MultiAgentState(AgentState):
    """State for the director's multi-agent workflow."""
    active_agent: NotRequired[DirectorStep]
    script_path: str
    caption_path: NotRequired[str]
    image_post_path: NotRequired[str]

class SMWriterState(AgentState):
    script: str
    caption_path: NotRequired[str]
    image_post_path: NotRequired[str]