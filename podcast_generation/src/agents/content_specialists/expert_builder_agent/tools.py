from langgraph.types import Command
from langchain_core.messages import ToolMessage
from langchain.tools import tool, ToolRuntime
import frontmatter, os
from dotenv import load_dotenv
from typing import List
from pathlib import Path

from .state import ExpertBuilderState
from ..utils import get_book_path

load_dotenv()

class ExpertProfileTools:

    @tool
    @staticmethod
    def read_persona(runtime: ToolRuntime[None, ExpertBuilderState]) -> Command:
        "Read the expert persona that has been drafted so far"
        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)
        try:
            with open(f"data/{title}/expert_persona.md", "r", encoding="utf-8") as f:
                persona_content = f.read()
        except:
            with open(f"data/{title}/expert_persona.md", "w", encoding="utf-8") as f:
                f.write("")

            with open(f"data/{title}/expert_persona.md", "r", encoding="utf-8") as f:
                persona_content = f.read()
        return Command(update={
            "messages": [ToolMessage(content=persona_content, tool_call_id=runtime.tool_call_id)],
            "persona_read": True,
        })

    @tool
    @staticmethod
    def edit_persona(to_replace: str, replace_with: str, runtime: ToolRuntime[None, ExpertBuilderState]) -> str:
        "Edit the expert persona in certain parts"
        if not runtime.state.get("persona_read"):
            return "Error: you must call read_persona before editing. Call it now."
        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)
        path = f"data/{title}/expert_persona.md"
        with open(path, "r", encoding="utf-8") as f:
            persona_content = f.read()
        count = persona_content.count(to_replace)
        if count == 0:
            return f"Error: old_string not found in {path}. Read the file again and copy the exact text to replace."
        if count > 1:
            return f"Error: old_string matches {count} locations in {path}. Include more surrounding context so it's unique."
        new_content = persona_content.replace(to_replace, replace_with)

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return "Persona updated!"          

    @tool
    @staticmethod
    def append_persona(content: str, runtime: ToolRuntime[None, ExpertBuilderState]) -> str:
        "Add further information to the end of the document about the expert persona"
        if not runtime.state.get("persona_read"):
            return "Error: you must call read_persona before editing. Call it now."
        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)

        with open(f"data/{title}/expert_persona.md", "a", encoding="utf-8") as f:
            f.write(content)

        return f"{content} - has been appended to the expert profile persona!"

    @tool
    @staticmethod
    def read_book_content(runtime: ToolRuntime[None, ExpertBuilderState], offset: int = 1, limit: int = 200) -> str:
        "Read the book's full parsed content by line range (1-indexed). Use this to read a passage in its natural paragraph flow when a retrieve_info chunk feels incomplete or cut off mid-argument."
        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)
        with open(f"data/{title}/book_content.md", "r", encoding="utf-8") as f:
            lines = f.readlines()
        start = max(offset - 1, 0)
        selected = lines[start:start + limit]
        return "".join(f"{i}\t{line}" for i, line in enumerate(selected, start=offset))

    @tool
    @staticmethod
    def load_skill_content(skill_name: str) -> str:
        "Load the content of the specific skill"
        post = frontmatter.load(f"src/skills/content_skills/expert_builder_agent/{skill_name}.md")
        return post.content

    @tool
    @staticmethod
    def load_available_skills() -> List[dict] | str:
        "Load the name and descriptions of the available skills"
        os.makedirs("src/skills/content_skills/expert_builder_agent", exist_ok=True)
        all_skills = list(Path("src/skills/content_skills/expert_builder_agent").glob("*.md"))
        if all_skills:
            all_metadata = []
            for skill in all_skills:
                post = frontmatter.load(skill)
                all_metadata.append(post.metadata)
            return all_metadata
        else:
            return "No skills available yet!"
