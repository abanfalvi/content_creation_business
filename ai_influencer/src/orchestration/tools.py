from langgraph.types import Command
from langchain_core.messages import ToolMessage, HumanMessage
from langchain.tools import tool, ToolRuntime

from langchain_openrouter import ChatOpenRouter
import wave, io, os, base64, time, httpx, uuid, json
from dotenv import load_dotenv
from typing import List, Optional, Literal
from openrouter import OpenRouter, utils
from pydantic import BaseModel, Field
from datetime import date

from ..cli.task_scheduler import set_daily_schedule, get_schedule_status, delete_schedule
from ..agents.utils import sum_usage, log_token_usage

load_dotenv()

from .state import OrchestratorState


def _persona_workflow_thread(runtime: ToolRuntime[None, OrchestratorState]) -> tuple[str, dict]:
    "Derive the sub-thread id/config persona_gen_workflow runs under for this orchestrator conversation."
    thread_id = f"{runtime.config["configurable"]["thread_id"]}:persona_gen_workflow"
    return thread_id, {"configurable": {"thread_id": thread_id}}


def _summarize_persona_result(persona_workflow: dict, pending_prefix: str) -> str:
    "Build the human-readable summary for a persona_gen_workflow result, whether paused for review or finished."
    interrupts = persona_workflow.get("__interrupt__")
    if interrupts:
        review = interrupts[0].value
        return (
            f"{pending_prefix}\n\n"
            f"Character:\n{review.get('character', 'N/A')}\n\n"
            f"Personality:\n{review.get('personality', 'N/A')}\n\n"
            f"Backstory:\n{review.get('backstory', 'N/A')}"
        )
    return (
        f"Finalized influencer: {persona_workflow.get('influencer_name', 'unknown')}\n\n"
        f"Character:\n{persona_workflow.get('character', 'N/A')}\n\n"
        f"Personality:\n{persona_workflow.get('personality', 'N/A')}\n\n"
        f"Backstory:\n{persona_workflow.get('backstory', 'N/A')}"
    )


class AgentTools:

    @tool
    def run_persona_creation_workflow(instruction: str, runtime: ToolRuntime[None, OrchestratorState]) -> Command:
        """Delegate to the Persona & Identity department to create a brand-new AI influencer from scratch.

        This runs the full persona creation workflow: character design, personality, and
        backstory generation, plus sample images. Partway through, the workflow pauses at a
        human review checkpoint and needs the drafted character/personality/backstory relayed
        to the user for approval (or revision feedback) before it can finish — once the user
        responds, call `submit_persona_review` (not this tool again) to relay their decision.
        Call this only when the user wants a new influencer to exist, not to modify or produce
        content for one that already exists, and not to relay review feedback on one already
        in progress.

        Args:
            instruction: The user's request or creative direction for the new influencer
                (e.g. desired niche, tone, or theme) — pass along what the user actually said
                rather than inventing details on their behalf.

        Returns:
            A Command updating the orchestrator's state with the new influencer's
            `influencer_name` and `voice_name` once the workflow completes.
        """
        from ..agents.persona_identity.persona_workflow import persona_gen_workflow

        thread_id, config = _persona_workflow_thread(runtime)

        if persona_gen_workflow.get_state(config).next:
            return Command(update={
                "messages": [
                    ToolMessage(
                        content="A persona review is already pending for this influencer — "
                                "call submit_persona_review with the user's decision instead of "
                                "starting a new workflow.",
                        tool_call_id=runtime.tool_call_id,
                    )
                ]
            })

        writer = runtime.stream_writer
        persona_workflow = {}
        for mode, data in persona_gen_workflow.stream({"prompt": instruction}, config=config, stream_mode=["values", "custom"]):
            if mode == "custom":
                writer(data) # {"node": "agent_node_name"} relayed straight up, unchanged
            elif mode == "values":
                persona_workflow = data

        # Token usage for this workflow is logged per specialist inside
        # persona_workflow.py itself (call_specialist_agent, gen_image_node,
        # call_review_router_node) — PersonaWorkflowState carries no `messages`
        # of its own to diff here; the actual LLM calls happen one level down,
        # each on its own separate checkpointed thread.

        summary = _summarize_persona_result(
            persona_workflow, "The persona draft is ready for human review before it can be finalized."
        )

        return Command(update={
            "messages": [
                ToolMessage(content=summary, tool_call_id=runtime.tool_call_id)
            ],
            "influencer_name": persona_workflow.get("influencer_name"),
            "voice_name": persona_workflow.get("voice_name")
        })

    @tool
    def submit_persona_review(approved: bool, runtime: ToolRuntime[None, OrchestratorState], feedback: str = "") -> Command:
        """Relay the user's decision on a persona draft that run_persona_creation_workflow paused for review.

        Call this once the user has responded to a pending persona review, and only then —
        calling it with no review pending is a no-op that reports there's nothing to resume.

        Args:
            approved: True if the user approved the draft as-is; False if they want changes.
            feedback: Required when approved is False — the user's specific revision request,
                relayed to whichever specialist (character/personality/backstory) it concerns.

        Returns:
            A Command updating the orchestrator's state once the workflow finalizes, or another
            round of review details if the revision itself needs re-approval.
        """
        from ..agents.persona_identity.persona_workflow import persona_gen_workflow

        thread_id, config = _persona_workflow_thread(runtime)

        if not persona_gen_workflow.get_state(config).next:
            return Command(update={
                "messages": [
                    ToolMessage(
                        content="There's no persona review currently pending — nothing to resume.",
                        tool_call_id=runtime.tool_call_id,
                    )
                ]
            })

        writer = runtime.stream_writer
        persona_workflow = {}
        for mode, data in persona_gen_workflow.stream(
            Command(resume={"approved": approved, "feedback": feedback}), config=config, stream_mode=["values", "custom"]
        ):
            if mode == "custom":
                writer(data)
            elif mode == "values":
                persona_workflow = data

        summary = _summarize_persona_result(
            persona_workflow, "The revised persona draft is ready for another round of human review."
        )

        return Command(update={
            "messages": [
                ToolMessage(content=summary, tool_call_id=runtime.tool_call_id)
            ],
            "influencer_name": persona_workflow.get("influencer_name"),
            "voice_name": persona_workflow.get("voice_name")
        })

    @tool
    async def call_content_production_manager(instruction: str, runtime: ToolRuntime[None, OrchestratorState]):
        """Delegate to the Content Production department manager to plan or produce content
        for the currently active influencer.

        Use this once an influencer persona already exists (`influencer_name` is set in state).
        The manager decides on its own whether the request needs calendar planning or actual
        content generation, and handles auditing internally — you only need to state the
        concrete content task.

        Args:
            instruction: The concrete content task to hand off (e.g. "plan next week's content"
                or "produce today's scheduled post"), not a vague instruction.

        Returns:
            The content manager's reported result for this task.
        """
        from ..agents.content_production.manager import get_content_manager_agent

        thread_id = runtime.config["configurable"]["thread_id"]
        content_manager_thread_id = f"{thread_id}:content_manager_agent"
        content_manager_agent = await get_content_manager_agent()
        snapshot = await content_manager_agent.aget_state({"configurable": {"thread_id": content_manager_thread_id}})
        before_count = len(snapshot.values.get("messages", [])) if snapshot.values else 0
        writer = runtime.stream_writer
        result = {}
        async for mode, data in content_manager_agent.astream({
                "messages": instruction,
                "influencer_name": runtime.state.get("influencer_name"),
                "voice_name": runtime.state.get("voice_name"),
                "active_step": "content_creation",
            },
            config={"configurable": {"thread_id": content_manager_thread_id}},
            stream_mode=["values", "custom"]):

            if mode == "custom":
                writer(data) # {"node": "agent_node_name"} relayed straight up, unchanged
            elif mode == "values":
                result = data

        turn_usage = sum_usage(result["messages"][before_count:])
        log_token_usage(
            "content_production",
            "content_manager",
            content_manager_thread_id,
            turn_usage.input_tokens,
            turn_usage.output_tokens
        )
        return result["messages"][-1].content

    @tool
    def call_response_engagement_agent(instruction: str, runtime: ToolRuntime[None, OrchestratorState]) -> str:
        "Delegate to the Engagement & Community department for the currently active influencer to get insights into how her content is performing online (e.g. recent media/Threads performance, engagement metrics). This only surfaces insights — it cannot be used to reply to audience comments, which is handled by a separate automated flow. `instruction` must state the concrete request. Requires an active influencer."
        from ..agents.engagement_community.specialist_agent import response_engagement_agent

        thread_id = runtime.config["configurable"]["thread_id"]
        config = {"configurable": {"thread_id": thread_id}}
        before_count = len(response_engagement_agent.get_state(config).values.get("messages", []))
        result = response_engagement_agent.invoke({
                "messages": instruction,
                "influencer_name": runtime.state.get("influencer_name"),
                "active_step": "get_insights",
            }, config={"configurable": {"thread_id": f"{thread_id}:response_engagement_agent"}})

        turn_usage = sum_usage(result["messages"][before_count:])
        log_token_usage(
            "engagement_community",
            "engagement_specialist",
            f"{thread_id}:response_engagement_agent",
            turn_usage.input_tokens,
            turn_usage.output_tokens
        )
        
        return result["messages"][-1].content

    @tool
    def manage_content_schedule(action: Literal["set", "status", "remove"], runtime: ToolRuntime[None, OrchestratorState], time: str = "") -> str:
        """Manage the OS-level daily schedule that runs content production unattended.

        This controls whether/when the agency automatically produces and publishes
        content once a day without anyone instructing you to — it does not itself
        produce content. Use "status" to check what's currently scheduled before
        assuming none exists. Confirm with the user before "remove", the same way
        you'd confirm before overwriting an active influencer — turning off automatic
        posting is easy to do accidentally and not obviously reversible from the
        user's side without asking you again.

        Args:
            action: "set" to create or change the daily run time, "status" to report
                the current schedule, "remove" to turn off automatic posting.
            time: Required when action is "set" — 24-hour "HH:MM" (e.g. "14:30" for
                2:30 PM). Ignored for "status" and "remove".

        Returns:
            A human-readable confirmation or status string to relay to the user.
        """
        if action == "set":
            if not time:
                return 'A time is required to set the schedule (24-hour "HH:MM", e.g. "14:30").'
            try:
                return set_daily_schedule(time)
            except ValueError as exc:
                return str(exc)
        elif action == "status":
            return get_schedule_status()
        else:
            return delete_schedule()

    @tool
    def read_persona_info(identity: Literal["CHARACTER", "PERSONALITY", "BACKSTORY"], runtime: ToolRuntime[None, OrchestratorState]) -> str:
        "Read the influencer's CHARACTER.md, PERSONALITY.md, or BACKSTORY.md file content"
        influencer_name = runtime.state.get("influencer_name")

        stored_persona_info = runtime.store.get(("content_production", influencer_name), identity.lower())
        if stored_persona_info:
            return json.dumps(stored_persona_info.value)

        persona_path = f"src/influencers/{influencer_name}/{identity}.md"

        with open(persona_path, "r", encoding="utf-8") as f:
            persona = f.read()

        return persona