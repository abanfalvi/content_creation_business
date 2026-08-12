from langgraph.types import Command
from langchain_core.messages import ToolMessage
from langchain.tools import tool, ToolRuntime
from typing import Literal

from .state import MultiAgentState
from .book_selection_agent import book_selection_agent
from .expert_builder_agent import expert_builder_agent
from .script_drafter_agent import script_drafter_agent


class DirectorTools:
    "List of tools for the Content Director agent"

    @tool("select_books", description="Find the next relevant book to work on")
    def call_book_selection_agent(query: str, runtime: ToolRuntime[None, MultiAgentState]):
        result = book_selection_agent.invoke({"messages": [{"role": "user", "content": query}]})
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
        result = expert_builder_agent.invoke({"messages": [{"role": "user", "content": query}]})
        summary = result["messages"][-1].content

        symbols = [":", " ", ","]
        for symbol in symbols:
            title = book_title.replace(symbol, "_")
        title = title.lower()
        with open("data/{title}/expert_persona.md", "r", encoding="utf-8") as f:
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
        result = script_drafter_agent.invoke({"messages": [{"role": "user", "content": query}]})
        return result["messages"][-1].content

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
