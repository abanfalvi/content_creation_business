from typing import List

from pydantic import BaseModel, Field
from typing_extensions import NotRequired

from langchain.agents import AgentState


class ManagerState(AgentState):
    influencer_name: str
    voice_name: str
    active_step: str
    verify_end_retries: NotRequired[int]


class HandOffContract(BaseModel):
    subtask_id: str = Field(description="Short unique identifier for this subtask, e.g. 'calendar-2026w35-tue'.")
    objective: str = Field(description="The single concrete goal the specialist must accomplish.")
    acceptance_criteria: List[str] = Field(description="Concrete, checkable conditions that must all be true for the output to be accepted.")
    constraints: List[str] = Field(description="Hard limits the specialist must respect (e.g. platform, tone, length, brand rules).")
    expected_outputs: List[str] = Field(description="The specific artifacts the specialist should produce (e.g. 'one Instagram caption', 'one 9:16 image').")
