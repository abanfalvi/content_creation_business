from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import List

class EngagementState(AgentState):
    influencer_name: str
    active_step: NotRequired[str]
    last_media_ids: NotRequired[List[str]]