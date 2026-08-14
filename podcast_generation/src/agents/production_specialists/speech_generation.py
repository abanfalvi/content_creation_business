# Workflow: 
# Separate the two speakers -> generate the audio for both

from dotenv import load_dotenv
import sqlite3
import opik
import re
from pydub import AudioSegment
import base64

from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import HumanMessage

from langgraph.types import interrupt

from opik.integrations.langchain import OpikTracer, track_langgraph

from .tools import VoiceAgentsTools
from .state import VoiceWorkflowState
from .audio_engineer_agent import audio_engineer_agent

from langgraph.graph import StateGraph, START, END

load_dotenv()

opik_tracer = OpikTracer()
opik.configure(workspace="dreadnought0073", project_name="podcast_generation")

def parse_turns(script_path: str) -> list[tuple[str, str]]:
    with open(script_path, encoding="utf-8") as f:
        text = f.read()
    return re.findall(r"\*\*(.+?):\*\*\s*(.+?)(?=\*\*|\Z)", text, re.S)

def build_episode(script_path: str, voice_map: dict[str, str], output_path: str) -> str:
    turns = parse_turns(script_path)
    episode = AudioSegment.empty()
    silence = AudioSegment.silent(duration=300)

    for i, (speaker, line) in enumerate(turns):
        clip_path = f"./tmp/turn_{i}.mp3"
        VoiceAgentsTools.generate_audio(line.strip(), voice=voice_map[speaker], output_path=clip_path)
        episode += AudioSegment.from_mp3(clip_path) + silence

    episode.export(output_path, format="mp3")
    return output_path

def call_audio_engineer_agent(audio_path: str, script: str):
    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

    message = HumanMessage(content=[
        {"type": "text", "text": f"Analyse this audio clip of a podcast episodes and make sure it has a smooth and natural flow. \n\n The following script was used:\n {script}"},
        {
            "type": "audio",
            "base64": audio_b64,
            "mime_type": "audio/mpeg",
        },
    ])
    result = audio_engineer_agent.invoke([message])
    return result["messages"][-1].content
    

def generate_podcast_audio_node(state: VoiceWorkflowState) -> dict:
    path = build_episode(
        state["script"], 
        voice_map={"Jordan": "536d3a5e000945adb7038665781a4aca", "Dr. Elias Thorne": "933563129e564b19a115bedd57b7406a"},
        output_path="data/contagious_why_things_catch_on/audio_contents/podcast_audio.mp3"
        )
    return {"audio_result": path}

def call_audio_engineer_agent_node(state: VoiceWorkflowState) -> dict:
    result = call_audio_engineer_agent(state["audio_result"], script=state["script"])

    return {"episode_result": state["rubric_scores"]["final_audio_path"], "rubric_scores": state["rubric_scores"]}

def human_review_node(state: VoiceWorkflowState) -> dict:
    decision = interrupt({
        "message": "Review the finished episode before ending the task.",
        "audio_path": state["episode_result"],
        "rubric": state.get("rubric_scores"),
    })
    if decision["approved"]:
        return {"status": "approved"}
    return {"status": "needs_revision", "feedback": decision.get("feedback")}


conn = sqlite3.connect("./checkpoints/production_checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)

builder = StateGraph(VoiceWorkflowState)
builder.add_node("generate_podcast_audio", generate_podcast_audio_node)
builder.add_node("call_audio_engineer_agent", call_audio_engineer_agent_node)
builder.add_node("human_review", human_review_node)

builder.add_edge(START, "generate_podcast_audio")
builder.add_edge("generate_expert_audio", "call_audio_engineer_agent")
builder.add_edge("call_audio_engineer_agent", "human_review")
builder.add_conditional_edges(
    "human_review", 
    lambda state: "publish" if state["status"] == "approved" else "audio_engineer",
    {"publish": END, "audio_engineer": "audio_engineer"},
    )

voice_gen_graph = builder.compile(checkpointer)

speech_gen_workflow = track_langgraph(voice_gen_graph, opik_tracer)
# speech_gen_workflow.invoke({"script": "", "audio_result": "", "final_audio": ""})

