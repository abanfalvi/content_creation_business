# Content Production Manager Agent
# Aim: Coordinate the work in the department
from dotenv import load_dotenv
from typing import Tuple, List, Callable
import opik, asyncio, json
from datetime import date
from opik.integrations.langchain import OpikTracer, track_langgraph
from pydantic import BaseModel, Field

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langgraph.types import Command
from langchain_core.messages import ToolMessage, HumanMessage
from langchain.tools import tool, ToolRuntime
from langchain.agents import AgentState
from typing_extensions import NotRequired
from langchain.agents.middleware.types import ModelRequest, ModelResponse

from ...models import CONTENT_PRODUCTION_MANAGER
from .specialists.content_strategist_agent.agent import content_strategist_agent
from .specialists.sm_writer_agent.agent import sm_content_writer_agent
from .utils import checkpointer, FileEditingTools
from .mcp import get_buffer_mcp
from ...auditor.agent import auditor_agent
from ...auditor.tools import AgentTools

class ManagerState(AgentState):
    influencer_name: str
    voice_name: str
    active_step: str
    img_url: NotRequired[str]
    audio_url: NotRequired[str]
    video_url: NotRequired[str]
    lipsynced: NotRequired[str]

class HandOffContract(BaseModel):
    subtask_id: str = Field(description="Short unique identifier for this subtask, e.g. 'calendar-2026w35-tue'.")
    objective: str = Field(description="The single concrete goal the specialist must accomplish.")
    acceptance_criteria: List[str] = Field(description="Concrete, checkable conditions that must all be true for the output to be accepted.")
    constraints: List[str] = Field(description="Hard limits the specialist must respect (e.g. platform, tone, length, brand rules).")
    expected_outputs: List[str] = Field(description="The specific artifacts the specialist should produce (e.g. 'one Instagram caption', 'one 9:16 image').")

class ManagerTools:

    @tool
    def call_content_strategist_agent(prompt: HandOffContract, runtime: ToolRuntime[None, ManagerState]) -> str:
        "Delegate to the Content Strategist Agent to plan, review, or update the influencer's content calendar (CALENDAR.json). `prompt` must state the concrete planning task (e.g. the window to plan, or the entry to revise), not a generic instruction."
        thread_id = runtime.config["configurable"]["thread_id"]
        result = content_strategist_agent.invoke(
            {"messages": prompt.model_dump_json(), "influencer_name": runtime.state.get("influencer_name")},
            config={"configurable": {"thread_id": f"{thread_id}:content_strategist_agent"}},
        )
        return result["messages"][-1].content

    @tool
    def call_sm_content_writer_agent(prompt: HandOffContract, runtime: ToolRuntime[None, ManagerState]) -> Command:
        "Delegate to the Social Media Content Writer Agent to produce one piece of content (image/video + caption). `prompt` must name the specific calendar entry or idea to execute, not a generic instruction."
        thread_id = runtime.config["configurable"]["thread_id"]
        result = sm_content_writer_agent.invoke(
            {"messages": prompt.model_dump_json(), "influencer_name": runtime.state.get("influencer_name"), "voice_name": runtime.state.get("voice_name")},
            config={"configurable": {"thread_id": f"{thread_id}:sm_content_writer_agent"}},
        )
        return Command(
            update={
                "messages": [
                    ToolMessage(content=result["messages"][-1].content, tool_call_id=runtime.tool_call_id),
                ],
                "audio_url": result.get("audio_url"),
                "img_url": result.get("img_url"),
                "video_url": result.get("video_url"),
                "lipsynced": result.get("lipsynced"),
                "active_step": "trace_auditing"
            }
        )

    @tool
    def read_content_calendar(runtime: ToolRuntime[None, ManagerState]) -> Tuple[str, str]:
        "Read the influencer's full CALENDAR.json so you can see what's already planned, in progress, or posted before delegating work or answering questions about the schedule."
        influencer_name = runtime.state.get("influencer_name")
        influencer_folder = f"src/influencers/{influencer_name}"
        with open(f"{influencer_folder}/CALENDAR.json", "r", encoding="utf-8") as f:
            content_calendar = json.load(f)
        content_calendar = "\n\n".join(
            f"{d}:\n" + "\n".join(
                f"  - [{entry['status']}] {entry['theme']} ({entry['content_type']}, {', '.join(entry['platforms'])})"
                for entry in entries
            )
            for d, entries in content_calendar.items()
        )

        return f"Today's date is: {str(date.today())}", content_calendar

    @tool
    def call_auditor(runtime: ToolRuntime[None, ManagerState]):
        "Call the auditor to analyse the traces took by the specialists agents"
        all_traces = {}
        for (name, agent) in [
            ("content_strategist_agent", content_strategist_agent),
            ("sm_content_writer_agent", sm_content_writer_agent),
        ]:
            agent_thread_id = f"{runtime.config["configurable"]["thread_id"]}:{name}"
    
            traces = AgentTools.extract_learnable_traces(thread_id=agent_thread_id, agent=agent, active_agent=name)
            result = auditor_agent.invoke({"messages": [("user", f"""
                        Analyse the following traces from {name} by collecting the steps that were successully
                        taken to solve the next part of the question AND should serve as a reinforcing
                        example of how this question/issue should be solved. 
                        In addition, make sure to collect those steps where the agent had troubles/failed
                        to successfully, or smoothly, solve the part of the question/issue at hand AND should
                        serve as a learning trace of what should be avoided in the future. 
            
                        Traces collected for this run: {traces}
    
                        Followingly, return back a summary of the traces you saved to the user.
            """)],
                "influencer_name": runtime.state.get("influencer_name"),
                "department_name": "content_production"
            })
            all_traces[name] = result["messages"][-1].content

        return all_traces


content_manager_model = ChatOpenRouter(
    model=CONTENT_PRODUCTION_MANAGER,
    temperature=0.2,
    max_tokens=2048
)

opik.configure(workspace="dreadnought0073", project_name="ai_influencer_agency", install_mcp=False)

with open(r"src\agents\content_production\SYSTEM_PROMPT.md", "r") as f:
    SYSTEM_PROMPT = f.read()

STEP_CONFIG = {
    "content_creation": {
        "tools": [
            ManagerTools.call_content_strategist_agent,
            ManagerTools.call_sm_content_writer_agent,
            ManagerTools.read_content_calendar
        ]
    },
    "trace_auditing": {
        "tools": [ManagerTools.call_auditor]
    }
}

@wrap_model_call
def apply_step_config(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """Configure agent behavior based on the current step."""
    active_agent = request.state.get("active_step")
    
    # Look up step configuration
    stage_config = STEP_CONFIG[active_agent]

    # Inject system prompt and step-specific tools
    request = request.override(
        tools=stage_config["tools"],
    )

    return handler(request)

async def build_content_manager_agent():
    sm_management_tools = await get_buffer_mcp()
    agent = create_agent(
        model=content_manager_model,
        tools=[
            ManagerTools.call_content_strategist_agent,
            ManagerTools.call_sm_content_writer_agent,
            ManagerTools.read_content_calendar,
            ManagerTools.call_auditor,
            # *sm_management_tools,
        ],
        system_prompt=SYSTEM_PROMPT,
        state_schema=ManagerState,
        checkpointer=checkpointer,
        )
    opik_tracer = OpikTracer()
    agent = track_langgraph(agent, opik_tracer)
    return agent

content_manager_agent = create_agent(
    model=content_manager_model,
    tools=[
        ManagerTools.call_content_strategist_agent,
        ManagerTools.call_sm_content_writer_agent,
        ManagerTools.read_content_calendar,
        ManagerTools.call_auditor,
        # *sm_management_tools,
    ],
    system_prompt=SYSTEM_PROMPT,
    state_schema=ManagerState,
    checkpointer=checkpointer,
    )
opik_tracer = OpikTracer()
content_manager_agent = track_langgraph(content_manager_agent, opik_tracer)

_content_manager_agent = None

def get_content_manager_agent():
    global _content_manager_agent
    if _content_manager_agent is None:
        _content_manager_agent = asyncio.run(build_content_manager_agent())
    return _content_manager_agent