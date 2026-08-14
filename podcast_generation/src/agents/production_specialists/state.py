from typing import TypedDict, Literal, Tuple
from langchain.agents import AgentState

class RubricScores(TypedDict):
    loudness_consistency: int
    noise_clarity: int
    silence_pacing: int
    transitions: int
    technical_compliance: int
    evidence: str
    final_audio_path: str

class VoiceWorkflowState(TypedDict):
    script: str
    audio_result: str
    # episode_result: str
    rubric_scores: RubricScores
    status: Literal["approved", "revise"]

class AudioEngineerState(AgentState):
    rubric_scores: RubricScores
