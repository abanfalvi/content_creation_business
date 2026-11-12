from typing import TypedDict, Literal
from langchain.agents import AgentState
from typing_extensions import NotRequired

class RubricScores(TypedDict):
    loudness_consistency: int
    noise_clarity: int
    silence_pacing: int
    transitions: int
    technical_compliance: int
    evidence: str
    final_audio_path: str

class AudioEngineerState(AgentState):
    active_step: NotRequired[Literal["edit_audio", "score_final_result"]]
    rubric_scores: RubricScores
