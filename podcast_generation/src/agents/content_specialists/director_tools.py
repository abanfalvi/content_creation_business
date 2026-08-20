from langgraph.types import Command, interrupt
from langchain_core.messages import ToolMessage
from langchain.tools import tool, ToolRuntime
from typing import Literal, Optional
import uuid

from .state import MultiAgentState
from .book_selection_agent import book_selection_agent
from .expert_builder_agent import expert_builder_agent
from .script_drafter_agent import script_drafter_agent
from .utils import get_book_path


class DirectorTools:
    "List of tools for the Content Director agent"

    @tool("select_books")
    def call_book_selection_agent(query: str, runtime: ToolRuntime[None, MultiAgentState]):
        "Find the next relevant book to work on"
        result = book_selection_agent.invoke({"messages": [{"role": "user", "content": query}]}, config={"configurable": {"thread_id": f"{runtime.execution_info.thread_id}::book_selection"}})
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=result["messages"][-1].content,
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "active_agent": "call_expert_builder_agent",
            }
        )

    @tool("build_expert_profile")
    def call_expert_builder_agent(query: str, runtime: ToolRuntime[None, MultiAgentState]):
        "Create an expert persona for the book"
        undesired_steps = runtime.store.search(("content_traces",), filter={"type": "failure", "agent_name": "expert_builder_agent"})
        if undesired_steps:
            query += f"\n\n Previously there might have been steps, which did not lead to the most desired or optimal solution, make sure to take them into account:\n {undesired_steps}"
        result = expert_builder_agent.invoke({"messages": [{"role": "user", "content": query}], "book_title": runtime.state.get("book_title")}, config={"configurable": {"thread_id": f"{runtime.execution_info.thread_id}::expert_builder"}})
        summary = result["messages"][-1].content

        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)
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

    @tool("draft_script")
    def call_script_drafter_agent(query: str, runtime: ToolRuntime[None, MultiAgentState]):
        "Draft the script for the next podcast episode"
        undesired_steps = runtime.store.search(("content_traces",), filter={"type": "failure", "agent_name": "script_drafter_agent"})
        if undesired_steps:
            query += f"\n\n Previously there might have been steps, which did not lead to the most desired or optimal solution, make sure to take them into account:\n {undesired_steps}"
        result = script_drafter_agent.invoke({"messages": [{"role": "user", "content": query}], "book_title": runtime.state.get("book_title")}, config={"configurable": {"thread_id": f"{runtime.execution_info.thread_id}::script_drafter"}})

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
    def edit_subagents_system_prompt(agent_name: Literal["book_selection_agent", "expert_builder_agent", "script_drafter_agent"], text_to_replace: str, text_to_replace_with: str, runtime: ToolRuntime[None, MultiAgentState]):
        "Edit the system prompt of a specific specialist agent"
        if not runtime.state.get("system_prompt_read"):
            return "Error: you must call read_subagents_system_prompt before editing. Call it now."
        path = f"src/agents/content_specialists/prompts/{agent_name}_prompt.md"
        with open(path, "r", encoding="utf-8") as f:
            agent_prompt = f.read()
        count = agent_prompt.count(text_to_replace)
        if count == 0:
            return f"Error: old_string not found in {path}. Read the file again and copy the exact text to replace."
        if count > 1:
            return f"Error: old_string matches {count} locations in {path}. Include more surrounding context so it's unique."
        new_content = agent_prompt.replace(text_to_replace, text_to_replace_with)

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return Command(update={
            "messages": [ToolMessage(content=f"{agent_name} system prompt has been updated", tool_call_id=runtime.tool_call_id)],
            "system_prompt_read": True,
        })

    @tool
    def read_subagents_system_prompt(agent_name: Literal["book_selection_agent", "expert_builder_agent", "script_drafter_agent"]):
        "Read the system prompt of a specific specialist agent"
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

    @tool("human_review")
    def human_review(runtime: ToolRuntime[None, MultiAgentState]):
        "Pause the workflow for the user's approve/reject decision on the drafted script"
        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)
        with open(f"data/{title}/script.md", "r", encoding="utf-8") as f:
            script_content = f.read()

        decision = interrupt({
            "action_requests": [{
                "name": "human_review",
                "args": {},
                "description": (
                    f"Review the drafted script for '{book_title}'. Resume with "
                    "{'approved': True} to accept, or "
                    "{'approved': False, 'feedback': '<what needs to change>'} to send it back.\n\n"
                    f"---\n{script_content}"
                ),
            }],
        })

        if decision.get("approved"):
            return Command(update={
                "messages": [ToolMessage(content="Script approved by the user.", tool_call_id=runtime.tool_call_id)],
                "active_agent": "get_lessons_learned",
            })

        feedback = decision.get("feedback") or "No specific feedback was given."
        return Command(update={
            "messages": [ToolMessage(content=f"Script rejected by the user. Feedback: {feedback}", tool_call_id=runtime.tool_call_id)],
            "active_agent": "full_flexibility",
        })


    @tool
    def save_learnable_traces(agent_name: Literal["expert_builder_agent", "script_drafter_agent"], success_trace: bool, title: str, description: str, content: Optional[str], avoid: Optional[str], prefer: Optional[str], runtime: ToolRuntime[None, MultiAgentState]):
        """
        Store both positive and undesired exemplary traces that can be used for improving the specialist agents

        Args:
        agent_name: str = which specialist agent this trace is about (the run may involve several; tag each trace with the one it actually applies to)
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
                "agent_name": agent_name,
                "Title": title, "Description": description, "Content": content,
            })
            return "Successful trace has been saved!"
        else:
            runtime.store.put(("content_traces",), str(uuid.uuid4()), {
                "type": "failure",
                "agent_name": agent_name,
                "Title": title, "Description": description, "Avoid": avoid, "Prefer": prefer
            })
            return "Undesired trace has been saved!"
