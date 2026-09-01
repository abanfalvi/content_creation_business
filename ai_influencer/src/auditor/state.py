from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import Literal

class AuditorState(AgentState):
    influencer_name: str
    department_name: Literal["persona_identity", "content_production", "engagement_community"]
    active_step: str
