
from dotenv import load_dotenv
import os
import re
from pydub import AudioSegment
import base64
from typing import Dict

from langchain_core.messages import HumanMessage
from langgraph.store.base import BaseStore
from langchain_core.runnables import RunnableConfig

from langgraph.types import interrupt


from .voice_tools import VoiceAgentsTools
from .state import VoiceWorkflowState
from .audio_engineer_agent.state import RubricScores
from .audio_engineer_agent.agent import audio_engineer_agent
from .lessons_learned_extractor.tools import LessonsLearnedExtracterAgentTools
from .lessons_learned_extractor.agent import build_lessons_learned_extractor_agent, build_extraction_request
from src.memory.memory_store import shared_store
from ..models import track
from .utils import checkpointer
from ..content_specialists.utils import get_book_path

from langgraph.graph import StateGraph, START, END

load_dotenv()


def parse_turns(script_path: str) -> list[tuple[str, str]]:
    with open(script_path, encoding="utf-8") as f:
        text = f.read()
    return re.findall(r"\*\*(.+?):\*\*\s*(.+?)(?=\*\*|\Z)", text, re.S)

def build_episode(script_path: str, voice_map: dict[str, str], output_path: str) -> str:
    turns = parse_turns(script_path)
    episode = AudioSegment.empty()
    silence = AudioSegment.silent(duration=300)

    os.makedirs("./tmp", exist_ok=True)
    for i, (speaker, line) in enumerate(turns):
        clip_path = f"tmp/turn_{i}.mp3" 
        VoiceAgentsTools.generate_audio(line.strip(), voice=voice_map[speaker], output_path=clip_path)
        episode += AudioSegment.from_mp3(clip_path) + silence

    episode.export(output_path, format="mp3")
    return output_path

def call_audio_engineer_agent(audio_path: str, script: str, thread_id: str, undesired_steps: Dict[str, str], user_feedback: str = "") -> tuple[str, RubricScores]:
    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

    with open(script, "r") as f:
        script_text = f.read()

    model_instruction = f"Analyse this audio clip of a podcast episodes and make sure it has a smooth and natural flow. \n\n Previously there might have been steps, which did not lead to the most desired or optimal solution, make sure to take them into account:\n {undesired_steps}"
    if user_feedback:
        model_instruction += f"\n\n The user did not approve the current version of the audio. Review the audio while taking into account their feedback: \n {user_feedback}"

    message = HumanMessage(content=[
        {"type": "text", "text": model_instruction},
    ])
    result = audio_engineer_agent.invoke({"messages": [message], "active_step": "edit_audio"}, config={"configurable": {"thread_id": thread_id}})

    rubric_score = audio_engineer_agent.invoke(
        {
            "messages": [HumanMessage(content="You're done editing this pass — finalize your quality assessment now.")],
            "active_step": "score_final_result",
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    return rubric_score["messages"][-1].content, rubric_score.get("rubric_scores")


def generate_podcast_audio_node(state: VoiceWorkflowState) -> dict:
    os.makedirs(f"data/{get_book_path(state['book_title'])}/audio_contents", exist_ok=True)
    path = build_episode(
        state["script"], 
        voice_map={"Jordan": "536d3a5e000945adb7038665781a4aca", state['expert_name']: "933563129e564b19a115bedd57b7406a"},
        output_path=f"data/{get_book_path(state['book_title'])}/audio_contents/podcast_audio.mp3"
        )
    return {"audio_result": path}

def call_audio_engineer_agent_node(state: VoiceWorkflowState, *, store: BaseStore, config: RunnableConfig) -> dict:
    audio_engineer_thread_id = f"{config['configurable']['thread_id']}:audio_engineer"
    _, rubric_scores = call_audio_engineer_agent(
        audio_path=state["audio_result"], 
        script=state["script"], 
        thread_id=audio_engineer_thread_id, 
        undesired_steps=store.search(("production_traces",), filter={"type": "failure"}),
        user_feedback=state["feedback"]
    )

    return {"episode_result": rubric_scores["final_audio_path"], "rubric_scores": rubric_scores}

def human_review_node(state: VoiceWorkflowState) -> dict:
    decision = interrupt({
        "message": "Review the finished episode before ending the task.",
        "audio_path": state["episode_result"],
        "rubric": state.get("rubric_scores"),
    })
    if decision["approved"]:
        return {"status": "approved"}
    return {"status": "needs_revision", "feedback": decision.get("feedback")}

def lessons_learned_node(state: VoiceWorkflowState, *, store: BaseStore, config: RunnableConfig) -> dict:
    audio_engineer_thread_id = f"{config['configurable']['thread_id']}:audio_engineer"

    ll_extracter_agent = build_lessons_learned_extractor_agent(store)

    traces = LessonsLearnedExtracterAgentTools.extract_learnable_traces(thread_id=audio_engineer_thread_id, agent=audio_engineer_agent)
    result = ll_extracter_agent.invoke({"messages": [("user", build_extraction_request(traces))]})

    return {"lessons_learned": result["messages"][-1].content}

builder = StateGraph(VoiceWorkflowState)
builder.add_node("generate_podcast_audio", generate_podcast_audio_node)
builder.add_node("call_audio_engineer_agent", call_audio_engineer_agent_node)
builder.add_node("human_review", human_review_node)
builder.add_node("lessons_learned_path", lessons_learned_node)

builder.add_edge(START, "generate_podcast_audio")
builder.add_edge("generate_podcast_audio", "call_audio_engineer_agent")
builder.add_edge("call_audio_engineer_agent", "human_review")
builder.add_conditional_edges(
    "human_review", 
    lambda state: "lessons_learned_path" if state["status"] == "approved" else "call_audio_engineer_agent",
    )
builder.add_edge("lessons_learned_path", END)

voice_gen_graph = builder.compile(checkpointer, store=shared_store)

speech_gen_workflow = track(voice_gen_graph)

