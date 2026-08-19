
import sqlite3

from langchain.agents import create_agent
from langchain.agents import AgentState
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse, HumanInTheLoopMiddleware, FilesystemFileSearchMiddleware, SummarizationMiddleware
from langgraph.graph import StateGraph, START, END
from langchain_openrouter import ChatOpenRouter

from typing import Literal, Callable
from typing_extensions import NotRequired

from .director_tools import DirectorTools
from .prompts import ContentDirectorPrompt
from .state import MultiAgentState
from ..models import DIRECTOR_MODEL
from ...memory.memory_store import shared_store
from .utils import checkpointer

with open("src/agents/content_specialists/prompts/director_agent_prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

director_model = ChatOpenRouter(
    model=DIRECTOR_MODEL,
    temperature=.1
)

# Step configuration: maps step name to (prompt, tools, required_state)
STEP_CONFIG = {
    "call_book_selection_agent": {
        "prompt": "",
        "tools": [DirectorTools.call_book_selection_agent],
        "requires": [],
    },
    "call_expert_builder_agent": {
        "prompt": "",
        "tools": [DirectorTools.call_expert_builder_agent],
        "requires": [],
    },
    "call_script_drafter_agent": {
        "prompt": "",
        "tools": [DirectorTools.call_script_drafter_agent],
        "requires": [],
    },
    # set current step/ active agent to this, when needed, during invoke method
    "edit_prompts": {
        "prompt": "",
        "tools": [DirectorTools.edit_subagents_system_prompt, DirectorTools.read_subagents_system_prompt],
        "requires": [],
    },
    "review_expert_profile": {
        "prompt": ContentDirectorPrompt.REVIEW_EXPERT_PROFILE,
        "tools": [DirectorTools.call_expert_builder_agent, DirectorTools.call_script_drafter_agent],
        "requires": [],
    },
    "get_lessons_learned": {
        "prompt": "",
        "tools": [DirectorTools.save_learnable_traces],
        "requires": [],
    },
}

def extract_learnable_traces(thread_id: str, agent):
    trace = []
    prev_len = 0

    history = list(agent.get_state_history({"configurable": {"thread_id": thread_id}}))
    for snapshot in reversed(history):
        messages = snapshot.values.get("active_agent")
        new_messages = messages[prev_len:]
        prev_len = len(messages)

        for msg in new_messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for call in msg.tool_calls:
                    trace.append({
                        "step": snapshot.metadata["step"],
                        "active_agent": snapshot.values.get("active_agent"),
                        "action": "called_tool",
                        "tool": call["name"],
                        "args": call["args"],
                    })
            elif type(msg).__name__ == "ToolMessage":
                trace.append({
                    "step": snapshot.metadata["step"],
                    "active_agent": snapshot.values.get("active_agent"),
                    "action": "tool_result",
                    "content": msg.content,
                })
            elif type(msg).__name__ == "AIMessage":
                trace.append({
                    "step": snapshot.metadata["step"],
                    "active_agent": snapshot.values.get("active_agent"),
                    "reasoning": "".join(b["reasoning"] for b in msg.content_blocks if b["type"] == "reasoning"),
                    "text": "".join(b["text"] for b in msg.content_blocks if b["type"] == "text"),

                    # "text": msg.text,
                    # "reasoning": msg.reasoning,
                })
    return trace

@wrap_model_call
def apply_step_config(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """Configure agent behavior based on the current step."""
    active_agent = request.state.get("active_agent", "call_book_selection_agent")
    thread_id = request.runtime.execution_info.thread_id

    # Look up step configuration
    stage_config = STEP_CONFIG[active_agent]

    # Validate required state exists
    for key in stage_config["requires"]:
        if request.state.get(key) is None:
            raise ValueError(f"{key} must be set before reaching {active_agent}")
    if active_agent == "get_lessons_learned":
        traces = extract_learnable_traces(thread_id, director_agent)
        step_prompt = f"""
            Analyse the following traces by collecting the steps that were successully
            taken to solve the next part of the question AND should serve as a reinforcing
            example of how this question/issue should be solved. 
            In addition, make sure to collect those steps where the agent had troubles/failed
            to successfully, or smoothly, solve the part of the question/issue at hand AND should
            serve as a learning trace of what should be avoided in the future. 

            Traces collected for this run: {traces}
            
        """
    else:
        step_prompt = stage_config["prompt"].format(
            **request.state
            )

    # Inject system prompt and step-specific tools
    if step_prompt:
        request = request.override(
            system_prompt=step_prompt,
            tools=stage_config["tools"],
        )
    else:
        request = request.override(
            tools=stage_config["tools"],
        )

    return handler(request)

all_tools = [
    DirectorTools.call_book_selection_agent,
    DirectorTools.call_expert_builder_agent,
    DirectorTools.call_script_drafter_agent,
    DirectorTools.read_subagents_system_prompt,
    DirectorTools.edit_subagents_system_prompt,
    DirectorTools.save_learnable_traces,
    DirectorTools.update_specialist_skills
]

director_agent = create_agent(
    model=director_model,
    tools=all_tools,
    system_prompt=SYSTEM_PROMPT,
    state_schema=MultiAgentState,
    middleware=[
        apply_step_config,
        HumanInTheLoopMiddleware(
            interrupt_on={"human_review": {"allowed_decisions": ["approve", "reject"]}},
            description_prefix="Final script pending approval",
        ),
        FilesystemFileSearchMiddleware(
            root_path="src/skills/distribution_skills",
            use_ripgrep=True,
        ),
    ],
    checkpointer=checkpointer,
    store=shared_store
)
