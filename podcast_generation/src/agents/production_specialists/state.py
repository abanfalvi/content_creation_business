from typing import TypedDict, Literal, Tuple
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

class VoiceWorkflowState(TypedDict):
    book_title: str
    script: str
    audio_result: str
    # episode_result: str
    rubric_scores: RubricScores
    status: Literal["approved", "revise"]
    lessons_learned: str

class AudioEngineerState(AgentState):
    rubric_scores: RubricScores

class LLExtractorState(AgentState):
    active_step: NotRequired[Literal["save_learnable_traces"]]