from langgraph.types import Command
from langchain_core.messages import ToolMessage, HumanMessage
from langchain.tools import tool, ToolRuntime

from langchain_core.documents import Document
import json, frontmatter, os, base64
from dotenv import load_dotenv
from typing import Optional, Literal

from ...utils import FileEditingTools, check_previous_influencers_persona
from .state import BackstoryState

load_dotenv()

class AgentTools:

    @tool
    def read_influencer_backstory(runtime: ToolRuntime[None, BackstoryState]) -> str:
        "Read the influencer's BACKSTORY.md file content"
        influencer_name = runtime.state.get("influencer_name")
        influencer_folder = f"src/influencers/{influencer_name}"
        if influencer_name:
            return FileEditingTools.read_file(f"src/influencers/{influencer_name}/BACKSTORY.md")
        else:
            with open(f"{influencer_folder}/BACKSTORY.md", "w") as f:
                f.write("")
            return FileEditingTools.read_file(f"src/influencers/{influencer_name}/BACKSTORY.md")

    @tool
    def append_content(content: str, runtime: ToolRuntime[None, BackstoryState]) -> str:
        "Append new content to the end of the influencer's BACKSTORY.md file"
        influencer_name = runtime.state.get("influencer_name")
        return FileEditingTools.append_filecontent(content, filepath=f"src/influencers/{influencer_name}/BACKSTORY.md")

    @tool
    def edit_influencer_backstory(to_replace: str, replace_with: str, runtime: ToolRuntime[None, BackstoryState]) -> str:
        "Replace an exact snippet of text in the influencer's BACKSTORY.md file with new text"
        influencer_name = runtime.state.get("influencer_name")
        return FileEditingTools.edit_filecontent(to_replace, replace_with, filepath=f"src/influencers/{influencer_name}/BACKSTORY.md")

    @tool
    def check_existing_influencers(runtime: ToolRuntime[None, BackstoryState]) -> str:
        "Check the already-designed character/personality/backstory summaries of every other existing influencer, so this one's life story, hometown, career path, and interests aren't too similar to any of them. Call before finalizing the Life Timeline and Consistency Anchors."
        influencer_name = runtime.state.get("influencer_name")
        return check_previous_influencers_persona(influencer_name, runtime.store)

