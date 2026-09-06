from langchain.agents import AgentState
from typing_extensions import NotRequired

class BackstoryState(AgentState):
    influencer_name: str
    artifact: NotRequired[str]