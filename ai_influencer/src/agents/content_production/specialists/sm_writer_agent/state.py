from langchain.agents import AgentState
from typing_extensions import NotRequired
from typing import List, Annotated
import operator

class ContentCreatorState(AgentState):
    influencer_name: str
    voice_name: str
    content_id: str
    img_url: NotRequired[Annotated[List[str], operator.add]]
    audio_url: NotRequired[str]
    audio_duration: NotRequired[float]
    video_url: NotRequired[str]
    lipsynced: NotRequired[str]