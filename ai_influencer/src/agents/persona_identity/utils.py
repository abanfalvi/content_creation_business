import frontmatter, os
from typing import List
from pathlib import Path
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver


conn = sqlite3.connect("./checkpoints/persona_identity.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)

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