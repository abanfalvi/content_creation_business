"""The real production LangGraph (TTS -> audio engineer -> human gate -> lessons), with its model-backed pieces stubbed.

This pins the contract the web app relies on: the audio gate's interrupt payload, and that
`episode_result` survives from the audio-engineer node to the review node.
"""
from types import SimpleNamespace

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from podcast_generation.agents.production_specialists import speech_generation as sg

RUBRIC = {"transitions": 4, "final_audio_path": "data/book/audio_contents/final.mp3"}


def test_audio_gate_payload_and_resume(monkeypatch):
    built = []
    monkeypatch.setattr(sg, "build_episode", lambda script, voice_map, output_path: built.append(output_path) or output_path)
    monkeypatch.setattr(sg, "call_audio_engineer_agent", lambda **kw: ("done", dict(RUBRIC, feedback_seen=kw["user_feedback"])))
    fake_extractor = SimpleNamespace(invoke=lambda *a, **k: {"messages": [SimpleNamespace(content="lessons saved")]})
    monkeypatch.setattr(sg, "build_lessons_learned_extractor_agent", lambda store: fake_extractor)
    monkeypatch.setattr(sg, "build_extraction_request", lambda traces: "x")
    monkeypatch.setattr(sg.LessonsLearnedExtracterAgentTools, "extract_learnable_traces", staticmethod(lambda **kw: []))

    graph = sg.builder.compile(MemorySaver(), store=InMemoryStore())
    config = {"configurable": {"thread_id": "t1"}}
    start = {"book_title": "A Book", "expert_name": "Dr. Sam", "script": "s.md", "audio_result": "", "feedback": ""}

    out = graph.invoke(start, config)
    payload = out["__interrupt__"][0].value
    assert payload["audio_path"] == RUBRIC["final_audio_path"]          # state key survived between nodes
    assert payload["rubric"]["transitions"] == 4 and payload["message"]
    assert built[0].endswith("a_book\\audio_contents\\podcast_audio.mp3") or built[0].endswith("a_book/audio_contents/podcast_audio.mp3")

    # rejecting loops back to the audio engineer with the feedback, then asks again
    out = graph.invoke(Command(resume={"approved": False, "feedback": "Too quiet"}), config)
    assert out["__interrupt__"][0].value["rubric"]["feedback_seen"] == "Too quiet"

    # approving runs the lessons step and finishes with the episode in state
    out = graph.invoke(Command(resume={"approved": True}), config)
    assert "__interrupt__" not in out
    assert out["episode_result"] == RUBRIC["final_audio_path"] and out["lessons_learned"] == "lessons saved"
