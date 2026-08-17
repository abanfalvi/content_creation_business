# Convert successful traces into skills + let the directors add to extend the capabilities of their specialists
from src.memory.memory_store import shared_store
from langchain_openrouter import ChatOpenRouter
from .agents.models import SKILL_CONVERTER_MODEL

from pydantic import BaseModel
from typing import Literal, Optional

skill_converter_model = ChatOpenRouter(
    model=SKILL_CONVERTER_MODEL,
    temperature=.1,
    max_tokens=8192,
)

class SkillSchema(BaseModel):
    agent_name: Optional[Literal['sm_writer_agent', 'publisher_agent', 'book_selection_agent', 'expert_builder_agent', 'script_drafter_agent']]
    skill_name: str
    skill_content: str

structured_model = skill_converter_model.with_structured_output(SkillSchema)  

def convert_to_skill(skill_name: Literal["content_traces", "production_traces", "distribution_traces"], book_title: str):
    successful_traces = shared_store.search((book_title, skill_name), filter={"type": "success"})

    for trace in successful_traces:
        converter_prompt = f"""
        Convert the following successful, reinforcing trace into a skill.md, so
        the next time the agent can easily recreate this successful step.

        Return your answer in the predefined schema. When creating the skill content,
        make sure to follow the latest best practices of writing SKILL files.

        Trace to work with: {trace}
        """

        outcome = structured_model.invoke(converter_prompt)
        if skill_name == "content_traces":
            with open(f"src/skills/content_skills/{outcome.agent_name}/{outcome.skill_name}.md") as f:
                f.write(outcome.skill_content)
        elif skill_name == "production_traces":
            with open(f"src/skills/production_skills/{outcome.skill_name}.md") as f:
                f.write(outcome.skill_content)
        elif skill_name == "distribution_traces":
            with open(f"src/skills/distribution_skills/{outcome.agent_name}/{outcome.skill_name}.md") as f:
                f.write(outcome.skill_content)