from typing import TypedDict, Literal, Optional, Dict
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

class PersonaWorkflowState(TypedDict):
    prompt: NotRequired[str]
    influencer_name: NotRequired[str]
    character: NotRequired[str]
    personality: NotRequired[str]
    backstory: NotRequired[str]
    voice_name: NotRequired[str]

    # rubric_scores: RubricScores
    agent_to_review: Optional[Literal["backstory_agent", "personality_agent", "character_design_agent"]]
    status: Literal["approved", "needs_revision"]
    feedback: Optional[str]
    lessons_learned: Dict[str, str]

class LLExtractorState(AgentState):
    active_step: NotRequired[Literal["save_learnable_traces"]]