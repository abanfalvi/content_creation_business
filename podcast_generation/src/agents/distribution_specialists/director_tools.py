from langgraph.types import Command
from langchain_core.messages import ToolMessage
from langchain.tools import tool, ToolRuntime
from typing import Literal, Optional
import uuid

from .state import MultiAgentState
from .sm_writer_agent import get_sm_writer_agent
from .publisher_agent import get_publisher_agent


class DirectorTools:
    "List of tools for the Distribution Director agent"

    @tool("draft_sm_content")
    async def call_sm_writer_agent(query: str, runtime: ToolRuntime[None, MultiAgentState]):
        "Draft the post promoting the next episode for social media"
        undesired_steps = runtime.store.search(("distribution_traces",), filter={"type": "failure", "active_agent": "sm_writer_agent"})
        if undesired_steps:
            query += f"\n\n Previously there might have been steps, which did not lead to the most desired or optimal solution, make sure to take them into account:\n {undesired_steps}"
        script_path = runtime.state.get("script_path")
        with open(script_path, "r", encoding="utf-8") as f:
            script = f.read()
        result = await get_sm_writer_agent().ainvoke({"messages": [{"role": "user", "content": query}], "script": script}, config={"thread_id": f"{runtime.execution_info.thread_id}::sm_writer_agent"})
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=result["messages"][-1].content,
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "active_agent": "review_post",
            }
        )

    @tool("publish_sm_post")
    async def call_publisher_agent(query: str, runtime: ToolRuntime[None, MultiAgentState]):
        "Publish the post to social media"
        undesired_steps = runtime.store.search(("distribution_traces",), filter={"type": "failure", "active_agent": "publisher_agent"})
        if undesired_steps:
            query += f"\n\n Previously there might have been steps, which did not lead to the most desired or optimal solution, make sure to take them into account:\n {undesired_steps}"
        result = await get_sm_writer_agent().ainvoke({"messages": [{"role": "user", "content": query}]}, config={"thread_id": f"{runtime.execution_info.thread_id}::publisher_agent"})

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=result["messages"][-1].content,
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "active_agent": "get_lessons_learned",
            }
        )

    @tool
    def edit_subagents_system_prompt(agent_name: Literal["sm_writer_agent", "publisher_agent"], to_replace: str, replace_with: str):
        "Edit the system prompt of a specific specialist agent"
        path = f"src/agents/distribution_specialists/prompts/{agent_name}_prompt.md"
        with open(path, "r", encoding="utf-8") as f:
            agent_prompt = f.read()
        count = agent_prompt.count(to_replace)
        if count == 0:
            return f"Error: old_string not found in {path}. Read the file again and copy the exact text to replace."
        if count > 1:
            return f"Error: old_string matches {count} locations in {path}. Include more surrounding context so it's unique."
        new_content = agent_prompt.replace(to_replace, replace_with)

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return f"{agent_name} system prompt has been updated"

    @tool
    def read_subagents_system_prompt(agent_name: Literal["sm_writer_agent", "publisher_agent"]):
        "Read the system prompt of a specific specialist agent"
        with open(f"src/agents/distribution_specialists/prompts/{agent_name}_prompt.md", "r", encoding="utf-8") as f:
            agent_prompt = f.read()
        return agent_prompt

    @tool
    def update_specialist_skills(agent_name: Literal["sm_writer_agent", "publisher_agent"], skill_name: str, updated_skill: str) -> str:
        "Use this tool when you need to refine any of the skills your specialist agents are using because they still produced undesired step even though there is a skill about it"
        path = f"src/skills/distribution_skills/{agent_name}/{skill_name}.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(updated_skill)
        return f"{skill_name} under {agent_name} as been updated successfully"

    @tool
    def save_learnable_traces(success_trace: bool, title: str, description: str, content: Optional[str], avoid: Optional[str], prefer: Optional[str], runtime: ToolRuntime[None, MultiAgentState]):
        """
        Store both positive and undesired exemplary traces that can be used for improving the specialist agents
        
        Args:
        book_title: str = name of the book that is being processed
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
            runtime.store.put(("distribution_traces",), str(uuid.uuid4()), {
                "type": "success",
                "active_agent": runtime.state.get("active_agent"),
                "Title": title, "Description": description, "Content": content,
            })
            return "Successful trace has been saved!"
        else:
            runtime.store.put(("distribution_traces",), str(uuid.uuid4()), {
                "type": "failure",
                "active_agent": runtime.state.get("active_agent"),
                "Title": title, "Description": description, "Avoid": avoid, "Prefer": prefer
            })
            return "Undesired trace has been saved!"
