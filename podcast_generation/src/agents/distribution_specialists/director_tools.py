from langgraph.types import Command
from langchain_core.messages import ToolMessage
from langchain.tools import tool, ToolRuntime
from typing import Literal

from .state import MultiAgentState
from .sm_writer_agent import sm_writer_agent
from .publisher_agent import publisher_agent


class DirectorTools:
    "List of tools for the Distribution Director agent"

    @tool("draft_sm_content", description="Draft the post promoting the next episode for social media")
    def call_sm_writer_agent(query: str, runtime: ToolRuntime[None, MultiAgentState]):
        result = sm_writer_agent.invoke({"messages": [{"role": "user", "content": query}]}, config={"thread_id": runtime.execution_info.thread_id})
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

    @tool("publish_sm_post", description="Publish the post to social media")
    def call_publisher_agent(query: str, runtime: ToolRuntime[None, MultiAgentState]):
        result = publisher_agent.invoke({"messages": [{"role": "user", "content": query}]}, config={"thread_id": runtime.execution_info.thread_id})

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
        with open(f"src/agents/distribution_specialists/prompts/{agent_name}_prompt.md", "r", encoding="utf-8") as f:
            agent_prompt = f.read()
        return agent_prompt

    @tool
    def save_learnable_traces(book_title: str, success_trace: bool, title: str, description: str, content: str, runtime: ToolRuntime[None, MultiAgentState]):
        """
        Store both positive and negative exemplary traces that can be used for improving the specialist agents
        
        Args:
        book_title = name of the book that is being processed
        success_trace = whether the current input is to reinforce a behaviour (True) or serve as a negative example (False)
        title = a concise summary of the core strategy (e.g., "Navigating Multi-Step Search Filters")
        description = one-sentence overview of the item's purpose
        content = detailed reasoning steps, decision rationales, and operational insights extracted from past experiences

        Output:
        Confirmation that your input has been saved to the persistent local store.
        """
        if success_trace:
            runtime.store.put(book_title, "Successful Trace", {"Title": title, "Description": description, "Content": content})
            return "Successful trace has been saved!"
        else:
            runtime.store.put(book_title, "Failed Trace", {"Title": title, "Description": description, "Content": content})
            return "Failed trace has been saved!"
