from langgraph.types import Command
from langchain_core.messages import ToolMessage, HumanMessage
from langchain.tools import tool, ToolRuntime

from langchain_openrouter import ChatOpenRouter
import wave, io, os, base64, time, frontmatter, uuid, json
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Optional, Literal
from openrouter import OpenRouter, utils
from datetime import date
from ..self_evolution import convert_to_skill

load_dotenv()

from .state import AuditorState

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

class AgentTools:

    @tool
    def save_learnable_traces(active_agent: str, success_trace: bool, title: str, description: str, content: Optional[str], avoid: Optional[str], prefer: Optional[str], runtime: ToolRuntime[None, AuditorState]):
        """
        Store both positive and undesired exemplary traces that can be used for improving the specialist agents
        
        Args:
        active_agent: str = name of the agent the traces belong to
        success_trace: bool = whether the current input is to reinforce a behaviour (True) or serve as a negative example (False)
        title: str = a concise summary of the core strategy (e.g., "Navigating Multi-Step Search Filters")
        description: str = one-sentence overview of the item's purpose
        content: str = detailed reasoning steps, decision rationales, and operational insights extracted from past experiences (Use this for desired steps that should be reinforced)
        avoid: str = description of what should be avoided and when (Use this only when you want to add undesired trace)
        prefer: str = description of what should be done instead of the behaviour that should be avoided (Use this only when you want to add undesired trace)

        Output:
        Confirmation that your input has been saved to the persistent local store.
        """
        if success_trace:
            runtime.store.put((runtime.state.get("department_name"), runtime.state.get("influencer_name"), "auditing"), str(uuid.uuid4()), {
                "type": "success",
                "active_agent": active_agent,
                "Title": title, "Description": description, "Content": content,
            })
            return "Successful trace has been saved!"
        else:
            runtime.store.put((runtime.state.get("department_name"), runtime.state.get("influencer_name"), "auditing"), str(uuid.uuid4()), {
                "type": "failure",
                "active_agent": active_agent,
                "Title": title, "Description": description, "Avoid": avoid, "Prefer": prefer
            })
            return "Undesired trace has been saved!"

    @tool
    def call_skill_converter(runtime: ToolRuntime[None, AuditorState]) -> str:
        "Convert this influencer's saved successful traces into reusable skill files for the relevant specialist agents, then remove those traces from the store."
        convert_to_skill(runtime.state.get("influencer_name"), runtime.state.get("department_name"), runtime.store)
        return "Your created success traces have been converted to skills and deleted from storage"

    @tool
    def read_existing_skills(agent_name: Literal['backstory_agent', 'character_design_agent', 'personality_agent', 'content_strategist_agent', 'sm_writer_agent'], skill_name: str = "") -> str:
        "Read the content of a specific skill file for the given specialist agent, by name. If you do not know the name of the specific skill, call the tool without, which will retrieve the list of skills belonging to the agent with their descriptions."
        os.makedirs(f"src/agents/content_production/specialists/{agent_name}/skills", exist_ok=True)
        if skill_name:
            with open(f"src/agents/content_production/specialists/{agent_name}/skills/{skill_name}.md", "r", encoding="utf-8") as f:
                data = f.read()
            return data
        else:
            skills = list(Path(f"src/agents/content_production/specialists/{agent_name}/skills").glob("*.md"))
            if skills:
                return "\n\n".join([SkillLoadingTools.load_skill_names(path) for path in skills])
            return "No skills found for this agent"


    @staticmethod
    def update_task_board(task: str, runtime: ToolRuntime[None, AuditorState]) -> str:
        with open(f"src/auditor/TASK_BOARD.json", "r", encoding="utf-8") as f:
            task_board = json.load(f)

        task_board.setdefault(runtime.state.get("today_date"), []).append({
            "id": str(uuid.uuid4()),
            "task": idea,
            "content_type": content_type,
            "platforms": platforms,
            "status": "PLANNED",
            "caption": "",
            "asset_filenames": [],
            "notes": notes
        })

    @staticmethod
    def read_task_board() -> str:
        with open(f"src/auditor/TASK_BOARD.json", "r", encoding="utf-8") as f:
            task_board = json.load(f)
        task_board = "\n\n".join(
            f"{d}:\n" + "\n".join(
                f"  - [{entry['status']}] {entry['theme']} ({entry['content_type']}, {', '.join(entry['platforms'])})"
                for entry in entries
            )
            for d, entries in task_board.items()
        )

        return f"Today's date is: {str(date.today())}", task_board

    @staticmethod
    def extract_learnable_traces(thread_id: str, agent, active_agent: str):
        trace = []
        prev_len = 0

        history = list(agent.get_state_history({"configurable": {"thread_id": thread_id}}))
        for snapshot in reversed(history):
            messages = snapshot.values.get("messages", [])
            new_messages = messages[prev_len:]
            prev_len = len(messages)

            for msg in new_messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for call in msg.tool_calls:
                        trace.append({
                            "step": snapshot.metadata["step"],
                            "active_agent": active_agent,
                            "action": "called_tool",
                            "tool": call["name"],
                            "args": call["args"],
                        })
                elif type(msg).__name__ == "ToolMessage":
                    trace.append({
                        "step": snapshot.metadata["step"],
                        "active_agent": active_agent,
                        "action": "tool_result",
                        "content": msg.content,
                    })
                elif type(msg).__name__ == "AIMessage":
                    trace.append({
                        "step": snapshot.metadata["step"],
                        "active_agent": active_agent,
                        "reasoning": "".join(b["reasoning"] for b in msg.content_blocks if b["type"] == "reasoning"),
                        "text": "".join(b["text"] for b in msg.content_blocks if b["type"] == "text"),
                    })
        return trace
        