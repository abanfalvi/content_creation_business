# Convert successful traces into skills + let the directors add to extend the capabilities of their specialists
from langchain_openrouter import ChatOpenRouter
from .models import SKILL_CONVERTER_MODEL, PERSONA_FALLBACK_MODEL_1, PERSONA_FALLBACK_MODEL_2

from pydantic import BaseModel
from typing import Literal, Optional
import os
from pathlib import Path

skill_converter_model = ChatOpenRouter(
    model=SKILL_CONVERTER_MODEL,
    temperature=.1,
    max_tokens=8192,
)
skill_converter_fallback_model_1 = ChatOpenRouter(model=PERSONA_FALLBACK_MODEL_1, temperature=.1, max_tokens=8192)
skill_converter_fallback_model_2 = ChatOpenRouter(model=PERSONA_FALLBACK_MODEL_2, temperature=.1, max_tokens=8192)

class SkillSchema(BaseModel):
    agent_name: Literal['backstory_agent', 'character_design_agent', 'personality_agent', 'content_strategist_agent', 'sm_writer_agent']
    skill_name: str
    skill_content: str

structured_model = skill_converter_model.with_structured_output(SkillSchema).with_fallbacks([
    skill_converter_fallback_model_1.with_structured_output(SkillSchema),
    skill_converter_fallback_model_2.with_structured_output(SkillSchema),
])

def convert_to_skill(current_influencer: str | None, department_name: Literal["persona_identity", "content_production", "engagement_community"], store) -> None:    
    successful_traces = store.search((department_name, current_influencer, "auditing"), filter={"type": "success"})

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
        applies to creating content not just the one this trace came from. 
        Do not name the specific influencer or any content unique to this one trace anywhere in the
        skill_name, description, or content — describe the transferable
        pattern (the tool sequence, the reasoning, the checks to run) only.

        Make sure to keep the skill name short, uppercase, and underscore_separated
        (no spaces) since it is used as the filename.

        Trace to work with: {trace}
        """
        for _ in range(3):
            try:
                outcome = structured_model.invoke(converter_prompt)
                outcome.skill_name = outcome.skill_name.strip().upper().replace(" ", "_")

                os.makedirs(f"src/agents/{department_name}/specialists/{outcome.agent_name}/skills", exist_ok=True)
                with open(f"src/agents/{department_name}/specialists/{outcome.agent_name}/skills/{outcome.skill_name}.md", "w") as f:
                    f.write(outcome.skill_content)
                store.delete((department_name, current_influencer, "auditing"), trace.key)
                break
            except Exception as e:
                print(e)
                continue