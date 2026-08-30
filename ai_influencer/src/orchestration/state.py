from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import Literal

class OrchestratorState(AgentState):
    influencer_name: NotRequired[str]
    area_of_speciality: NotRequired[str]
    voice_name: NotRequired[str]