from langchain.agents import AgentState
from typing_extensions import NotRequired

class ContentPlanningState(AgentState):
    influencer_name: str
    active_step: NotRequired[str]