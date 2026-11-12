from pathlib import Path
from typing import Any

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent

from langchain.agents.middleware import (SummarizationMiddleware,
                                         ModelFallbackMiddleware,
                                         after_agent, 
                                         AgentMiddleware,
                                         ToolCallLimitMiddleware
                                         )
from langchain.messages import HumanMessage

from .tools import ScriptDrafterTools
from ..shared_tools import SharedContentTools
from .state import ScriptDrafterState
from ...models import SCRIPT_DRAFTER_MODEL, COMPRESSOR_MODEL, track
from ..utils import checkpointer
from .revision_loop import revision_graph


MAX_VERIFY_ATTEMPTS = 2

with open(Path(__file__).parent / "prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

script_drafter_model = ChatOpenRouter(
    model=SCRIPT_DRAFTER_MODEL,
    temperature=0.3,
)

compressor_model = ChatOpenRouter(
    model=COMPRESSOR_MODEL,
    temperature=0.2,
)


# Collect all tools from all step configurations
all_tools = [
    ScriptDrafterTools.append_script,
    ScriptDrafterTools.edit_script,
    ScriptDrafterTools.read_script,
    ScriptDrafterTools.read_personas,
    ScriptDrafterTools.read_plan,
    SharedContentTools.retrieve_info,
    ScriptDrafterTools.load_available_skills,
    ScriptDrafterTools.load_skill_content,
    ScriptDrafterTools.compact_context_window
]

@after_agent(can_jump_to=["model"], state_schema=ScriptDrafterState)
def analyse_final_script(state: ScriptDrafterState, runtime):
    attempts = state.get("verify_attempts", 0)
    book_title = state.get("book_title")
    if attempts >= MAX_VERIFY_ATTEMPTS or not book_title:
        return None
    final = revision_graph.invoke({"book_title": book_title})
    instructions = final.get("revision_instructions")
    if instructions:
        return {
            "jump_to": "model",
            "verify_attempts": attempts + 1,
            "messages": [HumanMessage(instructions)]
        }
    else:
        return None

middleware: list[AgentMiddleware[Any, Any, Any]] = [
    ModelFallbackMiddleware(
        ChatOpenRouter(model="upstage/solar-pro4", temperature=0.3),
        ChatOpenRouter(model="deepseek/deepseek-v4-flash", temperature=0.3)
    ),
    analyse_final_script,
    ToolCallLimitMiddleware(tool_name="compact_context_window", run_limit=3)
]

script_drafter_agent = create_agent(
    script_drafter_model,
    tools=all_tools,
    state_schema=ScriptDrafterState,
    system_prompt=SYSTEM_PROMPT,
    middleware=middleware,
    checkpointer=checkpointer,
)

script_drafter_agent = track(script_drafter_agent)