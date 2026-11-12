from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import Literal

class LLExtractorState(AgentState):
    active_step: NotRequired[Literal["save_learnable_traces"]]
