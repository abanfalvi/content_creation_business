from langchain.agents import AgentState
from typing_extensions import NotRequired

class SMWriterState(AgentState):
    script: str
    caption_path: NotRequired[str]
    image_post_path: NotRequired[str]
