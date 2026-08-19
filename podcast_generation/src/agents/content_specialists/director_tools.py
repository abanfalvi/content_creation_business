from langgraph.types import Command
from langchain_core.messages import ToolMessage
from langchain.tools import tool, ToolRuntime
from typing import Literal, Optional
import uuid

from .state import MultiAgentState
from .book_selection_agent import book_selection_agent
from .expert_builder_agent import expert_builder_agent
from .script_drafter_agent import script_drafter_agent


class DirectorTools:
    "List of tools for the Content Director agent"

    @tool("select_books", description="Find the next relevant book to work on")
    def call_book_selection_agent(query: str, runtime: ToolRuntime[None, MultiAgentState]):
        result = book_selection_agent.invoke({"messages": [{"role": "user", "content": query}]}, config={"thread_id": runtime.execution_info.thread_id})
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=result["messages"][-1].content,
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "active_agent": "review_expert_profile",
            }
        )

    @tool("build_expert_profile", description="Create an expert persona for the book")
    def call_expert_builder_agent(query: str, book_title: str, runtime: ToolRuntime[None, MultiAgentState]):
        undesired_steps = runtime.store.search(("content_traces",), filter={"type": "failure", "active_agent": "expert_builder_agent"})
        query += f"\n\n Previously there might have been steps, which did not lead to the most desired or optimal solution, make sure to take them into account:\n {undesired_steps}"
        result = expert_builder_agent.invoke({"messages": [{"role": "user", "content": query}]}, config={"thread_id": runtime.execution_info.thread_id})
        summary = result["messages"][-1].content

        symbols = [":", " ", ","]
        for symbol in symbols:
            title = book_title.replace(symbol, "_")
        title = title.lower()
        with open(f"data/{title}/expert_persona.md", "r", encoding="utf-8") as f:
            persona_content = f.read()
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"{summary}\n\n---\nCurrent persona:\n{persona_content}",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "active_agent": "review_expert_profile",
            }
        )

    @tool("draft_script", description="Draft the script for the next podcast episode")
    def call_script_drafter_agent(query: str, runtime: ToolRuntime[None, MultiAgentState]):
        undesired_steps = runtime.store.search(("content_traces",), filter={"type": "failure", "active_agent": "script_drafter_agent"})
        query += f"\n\n Previously there might have been steps, which did not lead to the most desired or optimal solution, make sure to take them into account:\n {undesired_steps}"
        result = script_drafter_agent.invoke({"messages": [{"role": "user", "content": query}]}, config={"thread_id": runtime.execution_info.thread_id})
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=result["messages"][-1].content,
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "active_agent": "human_review",
            }
        )

    @tool
    def edit_subagents_system_prompt(agent_name: Literal["book_selection_agent", "expert_builder_agent", "script_drafter_agent"], to_replace: str, replace_with: str):
        path = f"src/agents/content_specialists/prompts/{agent_name}_prompt.md"
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
    def read_subagents_system_prompt(agent_name: Literal["book_selection_agent", "expert_builder_agent", "script_drafter_agent"]):
        with open(f"src/agents/content_specialists/prompts/{agent_name}_prompt.md", "r", encoding="utf-8") as f:
            agent_prompt = f.read()
        return agent_prompt

    @tool
    def update_specialist_skills(agent_name: Literal["expert_builder_agent", "script_drafter_agent"], skill_name: str, updated_skill: str) -> str:
        "Use this tool when you need to refine any of the skills your specialist agents are using because they still produced undesired step even though there is a skill about it"
        path = f"src/skills/content_skills/{agent_name}/{skill_name}.md"
        with open(path, "w") as f:
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
            runtime.store.put(("content_traces",), str(uuid.uuid4()), {
                "type": "success",
                "active_agent": runtime.state.get("active_agent"),
                "Title": title, "Description": description, "Content": content,
            })
            return "Successful trace has been saved!"
        else:
            runtime.store.put(("content_traces",), str(uuid.uuid4()), {
                "type": "failure",
                "active_agent": runtime.state.get("active_agent"),
                "Title": title, "Description": description, "Avoid": avoid, "Prefer": prefer
            })
            return "Undesired trace has been saved!"
