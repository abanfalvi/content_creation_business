
from dotenv import load_dotenv
import opik
import re
from pydub import AudioSegment
import base64

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langgraph.store.base import BaseStore
from langchain_core.runnables import RunnableConfig
from langchain_openrouter import ChatOpenRouter

from langgraph.types import interrupt

from opik.integrations.langchain import OpikTracer, track_langgraph

from .tools import VoiceAgentsTools, LessonsLearnedExtracterAgentTools
from .state import VoiceWorkflowState, RubricScores, LLExtractorState
from .audio_engineer_agent import audio_engineer_agent
from ...memory.memory_store import shared_store
from ..models import LL_EXTRACTOR_AGENT
from .utils import checkpointer

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

def call_audio_engineer_agent(audio_path: str, script: str, thread_id: str) -> tuple[str, RubricScores | None]:
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
    result = audio_engineer_agent.invoke([message], config={"configurable": {"thread_id": thread_id}})
    return result["messages"][-1].content, result.get("rubric_scores")


def generate_podcast_audio_node(state: VoiceWorkflowState) -> dict:
    path = build_episode(
        state["script"], 
        voice_map={"Jordan": "536d3a5e000945adb7038665781a4aca", "Dr. Elias Thorne": "933563129e564b19a115bedd57b7406a"},
        output_path=f"data/{state['book_title']}/audio_contents/podcast_audio.mp3"
        )
    return {"audio_result": path}

def call_audio_engineer_agent_node(state: VoiceWorkflowState, *, config: RunnableConfig) -> dict:
    audio_engineer_thread_id = f"{config['configurable']['thread_id']}:audio_engineer"
    _, rubric_scores = call_audio_engineer_agent(state["audio_result"], script=state["script"], thread_id=audio_engineer_thread_id)

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

    ll_extracter_agent = create_agent(
        model=ChatOpenRouter(model=LL_EXTRACTOR_AGENT, temperature=.2),
        tools=[LessonsLearnedExtracterAgentTools.save_learnable_traces],
        state_schema=LLExtractorState,
        store=store
    )

    traces = LessonsLearnedExtracterAgentTools.extract_learnable_traces(thread_id=audio_engineer_thread_id, agent=audio_engineer_agent)
    result = ll_extracter_agent.invoke({"messages": [("user", f"""
                Analyse the following traces by collecting the steps that were successully
                taken to solve the next part of the question AND should serve as a reinforcing
                example of how this question/issue should be solved. 
                In addition, make sure to collect those steps where the agent had troubles/failed
                to successfully, or smoothly, solve the part of the question/issue at hand AND should
                serve as a learning trace of what should be avoided in the future. 
    
                Traces collected for this run: {traces}

                Followingly, return back a summary of the traces you saved to the user.
    """)]})

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

speech_gen_workflow = track_langgraph(voice_gen_graph, opik_tracer)
# speech_gen_workflow.invoke({"script": "", "audio_result": "", "final_audio": "", "book_title": ""})

