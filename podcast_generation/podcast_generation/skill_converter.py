# Convert successful traces into skills + let the directors add to extend the capabilities of their specialists
from podcast_generation.settings import SKILLS_DIR
from podcast_generation.memory.memory_store import get_shared_store
from langchain_openrouter import ChatOpenRouter
from .agents.models import SKILL_CONVERTER_MODEL

from pydantic import BaseModel
from typing import Literal, Optional
import os

skill_converter_model = ChatOpenRouter(
    model=SKILL_CONVERTER_MODEL,
    temperature=.1,
    max_tokens=15000,
)

class SkillSchema(BaseModel):
    agent_name: Literal['book_selection_agent', 'expert_builder_agent', 'script_drafter_agent']
    skill_name: str
    skill_content: str

structured_model = skill_converter_model.with_structured_output(SkillSchema)  

def convert_to_skill(skill_name: Literal["content_traces", "production_traces"]):
    shared_store = get_shared_store()
    successful_traces = shared_store.search((skill_name,), filter={"type": "success"})

    for trace in successful_traces:
        converter_prompt = f"""
        Convert the following successful, reinforcing trace into a skill.md, so
        the next time the agent can easily recreate this successful step.

        Return your answer in the predefined schema. When creating the skill content,
        make sure to follow the latest best practices of writing SKILL files:
        - skill_content must start with YAML frontmatter delimited by "---" lines,
          containing at minimum a `name` field and a `description` field.
        - `description` must explain both what the skill does and when to use it.
        - Follow the frontmatter with a Markdown body (starting with a `# Title`)
          describing the workflow.

        The skill must be universal: write it as a generalizable workflow that
        applies to producing an episode from ANY book, not just
        the one this trace came from. Do not name the specific book, author,
        episode, or any content unique to this one trace anywhere in the
        skill_name, description, or content — describe the transferable
        pattern (the tool sequence, the reasoning, the checks to run) only.

        Make sure to keep the skill name short, lowercase, and underscore_separated
        (no spaces) since it is used as the filename.

        Trace to work with: {trace}
        """
        for attempt in range(3):
            try:
                outcome = structured_model.invoke(converter_prompt)
                outcome.skill_name = outcome.skill_name.strip().lower().replace(" ", "_")

                if skill_name == "content_traces":
                    os.makedirs(SKILLS_DIR / "content_skills" / f"{outcome.agent_name}", exist_ok=True)
                    with open(SKILLS_DIR / "content_skills" / f"{outcome.agent_name}/{outcome.skill_name}.md", "w") as f:
                        f.write(outcome.skill_content)
                elif skill_name == "production_traces":
                    os.makedirs(SKILLS_DIR / "content_skills" / f"{outcome.agent_name}", exist_ok=True)
                    with open(SKILLS_DIR / "production_skills" / f"{outcome.skill_name}.md", "w") as f:
                        f.write(outcome.skill_content)
                shared_store.delete((skill_name,), trace.key)
                break
            except Exception as e:
                print(e)
                continue