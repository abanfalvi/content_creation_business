from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import List

class ContentCreatorState(AgentState):
    influencer_name: str
    voice_name: str
    img_url: NotRequired[str]
    audio_url: NotRequired[str]
    audio_duration: NotRequired[float]
    video_url: NotRequired[str]
    lipsynced: NotRequired[str]
    reference_imgs: NotRequired[List[str]]