from langchain.agents import AgentState
from typing_extensions import NotRequired

class PersonalityState(AgentState):
    influencer_name: str
    voice_name: NotRequired[str]
    artifact: NotRequired[str]