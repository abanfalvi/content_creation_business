from langchain.agents import AgentState
from typing_extensions import NotRequired

class CharacterState(AgentState):
    influencer_name: NotRequired[str]
    # character_description: NotRequired[str]