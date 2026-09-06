import frontmatter, os, json
from typing import Any, List, Literal
from pathlib import Path
from json import JSONDecodeError
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.runtime import Runtime

from langchain.agents.middleware import after_agent
from langchain.agents.middleware.types import ToolCallRequest
from langchain.messages import HumanMessage

from langchain.agents import AgentState

conn = sqlite3.connect("./checkpoints/persona_identity.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)

def on_tool_error(exc: Exception, request: ToolCallRequest) -> str | None:
    if isinstance(exc, JSONDecodeError):
        return f"`{request.tool_call['name']}` failed; fix the input and retry. Following error returned: {exc}"
    return None

@after_agent(can_jump_to=["model"])
def verify_artifact(state: AgentState, runtime: Runtime) -> None | dict[str, Any]:
    influencer_name = state.get("influencer_name")
    artifact = state.get("artifact")
    with open(f"src/influencers/{influencer_name}/{artifact}.md", "r", encoding="utf-8") as f:
        data = f.read()
    if data:
        return None
    return {
        "jump_to": "model",
        "messages": [
            HumanMessage(content=(
                f"No artifact has been created for the {artifact} of this influencer {influencer_name}."
                "Make sure to create it before returning"
            ))
        ],
    }

class FileEditingTools:

    @staticmethod
    def read_file(filepath: str) -> str:
        with open(filepath, "r", encoding="utf-8") as f:
            data = f.read()

        return data

    @staticmethod
    def append_filecontent(content: str, filepath: str) -> str:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(content)

        return f"{content} has been appended to the file"

    @staticmethod
    def edit_filecontent(text_to_replace: str, new_text_to_add: str, filepath: str) -> str:
        with open(filepath, "r", encoding="utf-8") as f:
            data = f.read()

        count = data.count(text_to_replace)
        if count == 0:
            return f"Error: old_string not found in {filepath}. Read the file again and copy the exact text to replace."
        if count > 1:
            return f"Error: old_string matches {count} locations in {filepath}. Include more surrounding context so it's unique."
        new_content = data.replace(text_to_replace, new_text_to_add)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)

        return "The file has been successfully edited with your changes"

class SkillLoadingTools:

    def load_skill(skill_name: str, skill_path: str) -> str:
        "Load the content of the specific skill"
        try:
            post = frontmatter.load(f"{skill_path}/{skill_name}.md")
        except:
            return f"{skill_name} cannot be retrieved!"
        return post.content

    def load_skill_names(skill_path: str) -> List[dict] | str:
        "Load the name and descriptions of the available skills"
        os.makedirs(skill_path, exist_ok=True)
        all_skills = list(Path(skill_path).glob("*.md"))
        if all_skills:
            all_metadata = []
            for skill in all_skills:
                post = frontmatter.load(skill)
                all_metadata.append(post.metadata)
            return all_metadata
        else:
            return "No skills available yet!"

def check_previous_influencers_persona(current_influencer: str | None, store) -> str:
    """Summarize every other already-designed influencer's persona, pulling the
    distilled character/personality/backstory summaries Content Production
    already saved to the shared store (same ("content_production", name)
    namespace read_persona_info populates) rather than re-reading full .md
    files, so a new persona can be checked for overlap without flooding
    context with entire character bibles."""
    influencers_dir = Path("src/influencers")
    if not influencers_dir.exists():
        return "No other influencers exist yet — nothing to compare against."

    others = sorted(
        p.name for p in influencers_dir.iterdir()
        if p.is_dir() and p.name != current_influencer
    )
    if not others:
        return "No other influencers exist yet — nothing to compare against."

    profiles = []
    for name in others:
        sections = []
        for identity in ("character", "personality", "backstory"):
            stored = store.get(("content_production", name), identity)
            if stored:
                sections.append(f"{identity.upper()}: {json.dumps(stored.value)}")
        if sections:
            profiles.append(f"## {name}\n" + "\n".join(sections))

    if not profiles:
        return f"{len(others)} other influencer(s) exist ({', '.join(others)}), but none have a summarized persona yet."

    return "\n\n".join(profiles)
