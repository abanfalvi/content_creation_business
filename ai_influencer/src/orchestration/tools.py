from langgraph.types import Command
from langchain_core.messages import ToolMessage, HumanMessage
from langchain.tools import tool, ToolRuntime

from langchain_openrouter import ChatOpenRouter
import wave, io, os, base64, time, httpx, uuid, json
from dotenv import load_dotenv
from typing import List, Optional, Literal
from openrouter import OpenRouter, utils
import fal_client
from datetime import date

from ..agents.persona_identity.persona_workflow import persona_gen_workflow
from ..agents.content_production.manager import content_manager_agent

load_dotenv()

from .state import OrchestratorState

class AgentTools:

    @tool
    def run_persona_creation_workflow(instruction: str, runtime: ToolRuntime[None, OrchestratorState]) -> Command:
        """Delegate to the Persona & Identity department to create a brand-new AI influencer from scratch.

        This runs the full persona creation workflow: character design, personality, and
        backstory generation, plus sample images. Partway through, the workflow pauses at a
        human review checkpoint and needs the drafted character/personality/backstory relayed
        to the user for approval (or revision feedback) before it can finish. Call this only
        when the user wants a new influencer to exist, not to modify or produce content for
        one that already exists.

        Args:
            instruction: The user's request or creative direction for the new influencer
                (e.g. desired niche, tone, or theme) — pass along what the user actually said
                rather than inventing details on their behalf.

        Returns:
            A Command updating the orchestrator's state with the new influencer's
            `influencer_name` and `voice_name` once the workflow completes.
        """
        persona_workflow = persona_gen_workflow.invoke({"prompt": instruction})

        interrupts = persona_workflow.get("__interrupt__")
        if interrupts:
            review = interrupts[0].value
            summary = (
                "The persona draft is ready for human review before it can be finalized.\n\n"
                f"Character:\n{review.get('character', 'N/A')}\n\n"
                f"Personality:\n{review.get('personality', 'N/A')}\n\n"
                f"Backstory:\n{review.get('backstory', 'N/A')}"
            )
        else:
            summary = (
                f"Created influencer: {persona_workflow.get('influencer_name', 'unknown')}\n\n"
                f"Character:\n{persona_workflow.get('character', 'N/A')}\n\n"
                f"Personality:\n{persona_workflow.get('personality', 'N/A')}\n\n"
                f"Backstory:\n{persona_workflow.get('backstory', 'N/A')}"
            )

        return Command(update={
            "messages": [
                ToolMessage(content=summary, tool_call_id=runtime.tool_call_id)
            ],
            "influencer_name": persona_workflow.get("influencer_name"),
            "voice_name": persona_workflow.get("voice_name")
        })

    @tool
    def call_content_production_manager(instruction: str, runtime: ToolRuntime[None, OrchestratorState]):
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
        result = content_manager_agent.invoke({"messages": instruction, "influencer_name": runtime.state.get("influencer_name"), "voice_name": runtime.state.get("voice_name"), "active_step": "content_creation"})

        return result["messages"][-1].content
        