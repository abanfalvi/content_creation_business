"""An episode is named with one short LLM call from its sources and how it was asked for, like a chat is named."""
from types import SimpleNamespace

import pytest
from conftest import nb_url, wait_for
from test_combined import HABITS, WORK, write_source
from test_generation import (  # noqa: F401  (digests is an autouse fixture: it must be importable here too)
    SCRIPT, ScriptedGraph, add_ready_source, audio_gate, await_gate, digests, job, script_gate,
)

from podcast_generation.services import chat, formats, generation
from podcast_generation.settings import DATA_DIR

BRIEF = DATA_DIR / "deep_work" / formats.BRIEF_FILENAME


class TitleModel:
    """Stands in for the title model: records what it is asked and replies with a fixed text (or fails)."""

    def __init__(self, reply="Focus For Managers", error=None):
        self.reply, self.error, self.calls = reply, error, []

    def invoke(self, messages):
        self.calls.append([m.content for m in messages])
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.reply)


@pytest.fixture(autouse=True)
def no_leftover_brief():
    BRIEF.unlink(missing_ok=True)
    yield
    BRIEF.unlink(missing_ok=True)


def run_to_done(client, monkeypatch, tmp_path, payload, slug="deep_work"):
    """Start a run with these scripted agents, approve both gates and return the finished job and its episode."""
    audio = tmp_path / "podcast_audio.mp3"
    audio.write_bytes(b"ID3")

    def write_script():
        (DATA_DIR / slug / "script.md").write_text(SCRIPT, encoding="utf-8")
        return script_gate()

    content = ScriptedGraph(write_script, {"messages": []})
    production = ScriptedGraph(audio_gate(audio), lambda: {"episode_result": str(audio)})
    monkeypatch.setattr(generation, "get_content_director", lambda: content)
    monkeypatch.setattr(generation, "get_production_workflow", lambda: production)

    started = client.post("/api/generate", json=payload).json()
    await_gate(client, started["id"], "script")
    client.post(f"/api/jobs/{started['id']}/decision", json={"approved": True})
    await_gate(client, started["id"], "audio")
    client.post(f"/api/jobs/{started['id']}/decision", json={"approved": True})
    done = wait_for(lambda: (j := job(client, started["id"]))["status"] == "done" and j)
    episode = next(e for e in client.get(nb_url(client, "episodes")).json() if e["id"] == done["result"]["episode_id"])
    return done, episode, content


def test_a_plain_run_keeps_the_source_title_without_a_model_call(client, monkeypatch, tmp_path):
    add_ready_source(client, monkeypatch)
    model = TitleModel()
    monkeypatch.setattr(chat, "build_title_model", lambda: model)

    done, episode, _ = run_to_done(client, monkeypatch, tmp_path, {"source_slug": "deep_work"})

    assert model.calls == [] and "episode_title" not in done["result"]
    assert episode["title"] == "Deep Work"


def test_an_episode_is_named_from_its_source_format_and_instructions(client, monkeypatch, tmp_path):
    add_ready_source(client, monkeypatch)
    model = TitleModel('"Deep Focus For Managers."')
    monkeypatch.setattr(chat, "build_title_model", lambda: model)

    done, episode, content = run_to_done(client, monkeypatch, tmp_path, {
        "source_slug": "deep_work", "format": "debate", "instructions": "Focus on what this means for managers"})

    assert len(model.calls) == 1
    system, human = model.calls[0]
    assert "At most 6 words" in system
    assert "Sources: Deep Work" in human and "Format: Debate" in human and "Focus on what this means for managers" in human
    assert episode["title"] == done["result"]["episode_title"] == "Deep Focus For Managers"  # quotes and the full stop are dropped
    assert content.inputs[0]["book_title"] == "Deep Work"  # the agents still work on the source, not on the episode's name


def test_the_name_is_available_while_the_run_is_in_progress(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    monkeypatch.setattr(chat, "build_title_model", lambda: TitleModel("Focus, Critically"))
    monkeypatch.setattr(generation, "get_content_director", lambda: ScriptedGraph(script_gate()))

    started = client.post("/api/generate", json={"source_slug": "deep_work", "format": "critical_overview"}).json()
    gate = await_gate(client, started["id"], "script")

    assert gate["result"]["episode_title"] == "Focus, Critically"  # the card and the review dialog can show it


def test_a_custom_description_is_given_to_the_model(client, monkeypatch, tmp_path):
    add_ready_source(client, monkeypatch)
    model = TitleModel("A Week Of Focus")
    monkeypatch.setattr(chat, "build_title_model", lambda: model)

    _, episode, _ = run_to_done(client, monkeypatch, tmp_path, {
        "source_slug": "deep_work", "format": "custom", "format_description": "Three short segments, ending on one thing to try"})

    assert "Three short segments, ending on one thing to try" in model.calls[0][1]
    assert episode["title"] == "A Week Of Focus"


def test_a_long_reply_is_cut_to_six_words(client, monkeypatch, tmp_path):
    add_ready_source(client, monkeypatch)
    monkeypatch.setattr(chat, "build_title_model", lambda: TitleModel("One Two Three Four Five Six Seven Eight"))

    _, episode, _ = run_to_done(client, monkeypatch, tmp_path, {"source_slug": "deep_work", "format": "brief"})

    assert episode["title"] == "One Two Three Four Five Six"


@pytest.mark.parametrize("failure", [RuntimeError("offline"), None])
def test_if_naming_fails_a_non_default_format_is_told_apart_by_its_label(client, monkeypatch, tmp_path, failure):
    add_ready_source(client, monkeypatch)
    monkeypatch.setattr(chat, "build_title_model", lambda: TitleModel(reply="  ", error=failure))  # an error, or an empty reply

    done, episode, _ = run_to_done(client, monkeypatch, tmp_path, {"source_slug": "deep_work", "format": "debate"})

    assert done["status"] == "done" and episode["title"] == "Deep Work · Debate"


def test_naming_failure_in_the_default_format_keeps_the_source_title(client, monkeypatch, tmp_path):
    add_ready_source(client, monkeypatch)
    monkeypatch.setattr(chat, "build_title_model", lambda: TitleModel(error=RuntimeError("offline")))

    done, episode, _ = run_to_done(client, monkeypatch, tmp_path, {"source_slug": "deep_work", "instructions": "For beginners"})

    assert done["status"] == "done" and episode["title"] == "Deep Work"


def test_a_combined_episode_is_named_from_all_its_sources_without_renaming_the_run(client, monkeypatch, tmp_path):
    add_ready_source(client, monkeypatch, "Deep_Work.pdf")
    add_ready_source(client, monkeypatch, "Atomic_Habits.pdf")
    write_source("deep_work", WORK)
    write_source("atomic_habits", HABITS)
    combined_slug, combined_title = "deep_work_+_atomic_habits", "Deep Work + Atomic Habits"
    model = TitleModel("Focus And Habits")
    monkeypatch.setattr(chat, "build_title_model", lambda: model)

    done, episode, content = run_to_done(
        client, monkeypatch, tmp_path, {"source_slugs": ["deep_work", "atomic_habits"]}, slug=combined_slug)

    assert "Sources: Deep Work; Atomic Habits" in model.calls[0][1]  # called although the format is the default
    assert episode["title"] == "Focus And Habits"
    assert done["result"]["title"] == combined_title and done["slug"] == combined_slug  # the run's identity is untouched
    assert content.inputs[0]["book_title"] == combined_title
