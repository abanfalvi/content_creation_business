from typing import TypedDict, Literal, Optional, List
from langchain.agents import AgentState

class QAChatAgentState(AgentState):
    chunks_read: List[str]

    book_title: str
    expert_name: str 
    script: str
    audio_result: str
    episode_result: str
    status: Literal["approved", "needs_revision"]
    feedback: Optional[str]
    lessons_learned: str
