import json
import threading
from datetime import date
from typing import Tuple

from langgraph.types import Command
from langchain_core.messages import ToolMessage
from langchain.tools import tool, ToolRuntime

from .state import ManagerState, HandOffContract
from ..specialists.content_strategist_agent.agent import content_strategist_agent
from ..specialists.sm_writer_agent.agent import sm_content_writer_agent
from ....auditor.agent import auditor_agent
from ....auditor.tools import AgentTools
from ....agents.utils import sum_usage, log_token_usage

_calendar_lock = threading.Lock()


class ManagerTools:

    @tool
    def call_content_strategist_agent(prompt: HandOffContract, runtime: ToolRuntime[None, ManagerState]) -> str:
        "Delegate to the Content Strategist Agent to plan, review, or update the influencer's content calendar (CALENDAR.json). `prompt` must state the concrete planning task (e.g. the window to plan, or the entry to revise), not a generic instruction."
        runtime.stream_writer({"step": "call_content_strategist_agent"})
        thread_id = runtime.config["configurable"]["thread_id"]
        config = {"configurable": {"thread_id": f"{thread_id}:content_strategist_agent"}}
        before_count = len(content_strategist_agent.get_state(config).values.get("messages", []))
        result = content_strategist_agent.invoke(
            {"messages": prompt.model_dump_json(), "influencer_name": runtime.state.get("influencer_name")},
            config=config,
        )
        turn_usage = sum_usage(result["messages"][before_count:])
        log_token_usage("content_production", "content_strategist_agent", config["configurable"]["thread_id"], turn_usage.input_tokens, turn_usage.output_tokens)
        return result["messages"][-1].content

    @tool
    def call_sm_content_writer_agent(prompt: HandOffContract, content_id: str, runtime: ToolRuntime[None, ManagerState]) -> Command:
        "Delegate to the Social Media Content Writer Agent to produce one piece of content (image/video + caption). `prompt` must name the specific calendar entry or idea to execute, not a generic instruction. Also add the content id in your instruction. The produced asset URL(s) are recorded onto that calendar entry automatically — call `read_content_calendar` afterward to retrieve them (e.g. before publishing via Buffer), rather than expecting them in this tool's result."
        runtime.stream_writer({"step": "call_sm_content_writer_agent"})
        thread_id = runtime.config["configurable"]["thread_id"]
        config = {"configurable": {"thread_id": f"{thread_id}:sm_content_writer_agent"}}
        before_count = len(sm_content_writer_agent.get_state(config).values.get("messages", []))
        result = sm_content_writer_agent.invoke(
            {"messages": prompt.model_dump_json(), "influencer_name": runtime.state.get("influencer_name"), "voice_name": runtime.state.get("voice_name"), "content_id": content_id},
            config=config,
        )
        turn_usage = sum_usage(result["messages"][before_count:])
        log_token_usage("content_production", "sm_content_writer_agent", config["configurable"]["thread_id"], turn_usage.input_tokens, turn_usage.output_tokens)

        return Command(
            update={
                "messages": [
                    ToolMessage(content=result["messages"][-1].content, tool_call_id=runtime.tool_call_id),
                ],
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
                f"  - {entry['id']} [{entry['status']}] {entry['theme']} ({entry['content_type']}, {', '.join(entry['platforms'])}), \nCaption: {entry["caption"]}"
                + (f"\n    asset_links: {', '.join(entry['asset_links'])}" if entry.get("asset_links") else "")
                for entry in entries
            )
            for d, entries in content_calendar.items()
        )

        return f"Today's date is: {str(date.today())}", content_calendar

    @tool
    def mark_posted(content_id: str, date: str, runtime: ToolRuntime[None, ManagerState]):
        "Mark the calendar entry with the given id, under the given date, as POSTED"
        influencer_name = runtime.state.get("influencer_name")
        calendar_path = f"src/influencers/{influencer_name}/CALENDAR.json"

        with _calendar_lock:
            with open(calendar_path, "r", encoding="utf-8") as f:
                content_calendar = json.load(f)

            for date_time, content in content_calendar.items():
                if date_time == date:
                    for c in content:
                        if c["id"] == content_id:
                            c["status"] = "POSTED"
                            break

            with open(calendar_path, "w", encoding="utf-8") as f:
                json.dump(content_calendar, f, indent=2)

        return Command(update={
            "messages": [
                ToolMessage(content=f"{content_id} has been set to POSTED", tool_call_id=runtime.tool_call_id)
            ],
            "active_step": "trace_auditing"
        })

    @tool
    def call_auditor(runtime: ToolRuntime[None, ManagerState]):
        "Call the auditor to analyse the traces took by the specialists agents"
        runtime.stream_writer({"step": "call_auditor"})
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
                "department_name": "content_production",
                "active_step": "save_traces"
            })
            # auditor_agent has no checkpointer (see auditor/agent.py) — each
            # .invoke() call is stateless, so its full result already is this
            # call's usage, with nothing prior to slice off.
            turn_usage = sum_usage(result["messages"])
            log_token_usage("content_production", "auditor", agent_thread_id, turn_usage.input_tokens, turn_usage.output_tokens)
            all_traces[name] = result["messages"][-1].content

        return all_traces
