from typing import TypedDict, Literal, Optional

from .audio_engineer_agent.state import RubricScores

class VoiceWorkflowState(TypedDict):
    book_title: str
    expert_name: str 
    script: str
    audio_result: str
    # episode_result: str
    rubric_scores: RubricScores
    status: Literal["approved", "revise"]
    feedback: Optional[str]
    lessons_learned: str
