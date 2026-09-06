from langgraph.types import Command
from langchain_core.messages import ToolMessage
from langchain.tools import tool, ToolRuntime

from langchain_core.documents import Document
import json, frontmatter, os
from dotenv import load_dotenv
from typing import Optional
from pathlib import Path

from ...utils import FileEditingTools, check_previous_influencers_persona
from .state import CharacterState

load_dotenv()

class AgentTools:

    @tool
    def create_influencer_files(full_name: str, runtime: ToolRuntime[None, CharacterState]) -> Command:
        "Create the influencer's folder along with empty CHARACTER.md, PERSONALITY.md, and BACKSTORY.md files, and store the influencer's name in state"
        name = full_name.strip().lower().replace(" ", "_")
        os.makedirs(f"src/influencers/{name}", exist_ok=True)
        influencer_folder = f"src/influencers/{name}"
        with open(f"{influencer_folder}/CHARACTER.md", "w") as f:
            f.write("")

        with open(f"{influencer_folder}/PERSONALITY.md", "w") as f:
            f.write("")

        with open(f"{influencer_folder}/BACKSTORY.md", "w") as f:
            f.write("")

        with open(f"{influencer_folder}/CALENDAR.json", "w") as f:
            json.dump({}, f)

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="Influencer folder and character design files were successfully created",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "influencer_name": name,
            }
        )

    @tool
    def read_character_design(runtime: ToolRuntime[None, CharacterState]) -> str:
        "Read the influencer's CHARACTER.md file content"
        influencer_name = runtime.state.get("influencer_name")
        if influencer_name:
            return FileEditingTools.read_file(f"src/influencers/{influencer_name}/CHARACTER.md")
        else:
            return "Influencer name has not been defined, call create_influencer_files first!"

    @tool
    def append_content(content: str, runtime: ToolRuntime[None, CharacterState]) -> str:
        "Append new content to the end of the influencer's CHARACTER.md file"
        influencer_name = runtime.state.get("influencer_name")
        return FileEditingTools.append_filecontent(content, filepath=f"src/influencers/{influencer_name}/CHARACTER.md")

    @tool
    def edit_character_design(to_replace: str, replace_with: str, runtime: ToolRuntime[None, CharacterState]) -> str:
        "Replace an exact snippet of text in the influencer's CHARACTER.md file with new text"
        influencer_name = runtime.state.get("influencer_name")
        return FileEditingTools.edit_filecontent(to_replace, replace_with, filepath=f"src/influencers/{influencer_name}/CHARACTER.md")

    @tool
    def check_existing_influencers(runtime: ToolRuntime[None, CharacterState]) -> str:
        "Check the already-designed character/personality/backstory summaries of every other existing influencer, so this one's visual identity (archetype, vibe, coloring, style) isn't too similar to any of them. Call before finalizing the Identity Snapshot and Consistency Anchors."
        influencer_name = runtime.state.get("influencer_name")
        return check_previous_influencers_persona(influencer_name, runtime.store)
