"""One episode from several sources: the combined source file, the run's job, and retrieval across the members."""
from types import SimpleNamespace

import pytest
from conftest import nb_url, wait_for
from test_generation import (  # noqa: F401  (digests is an autouse fixture: it must be importable here too)
    SCRIPT, ScriptedGraph, add_ready_source, audio_gate, await_gate, digests, job, script_gate,
)

from podcast_generation.agents.content_specialists import shared_tools
from podcast_generation.book_preprocessing import combined
from podcast_generation.book_preprocessing.source_meta import book_file, read_meta
from podcast_generation.services import generation
from podcast_generation.settings import DATA_DIR

WORK = "# Deep Work\n\nFocus is a skill.\nIt can be trained."
HABITS = "# Atomic Habits\n\nSmall changes compound.\n"


def write_source(slug: str, text: str) -> None:
    path = book_file(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def rows():
    return [
        {"slug": "deep_work", "title": "Deep Work", "author": "Cal Newport", "indexed": 1},
        {"slug": "atomic_habits", "title": "Atomic Habits", "author": "", "indexed": 0},
    ]


def test_combined_source_indexes_the_lines_of_every_source():
    write_source("deep_work", WORK)
    write_source("atomic_habits", HABITS)

    slug, title = combined.prepare_combined_source(rows())

    assert title == "Deep Work + Atomic Habits" and slug == "deep_work_+_atomic_habits"
    lines = book_file(slug).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Combined source: Deep Work + Atomic Habits"
    for i, (name, a, b) in enumerate([("Deep Work", None, None), ("Atomic Habits", None, None)], start=1):
        entry = next(line for line in lines if line.startswith(f"{i}. {name}"))
        a, b = (int(n) for n in entry.rsplit("lines ", 1)[1].split("-"))
        assert lines[a - 1] == f"=== SOURCE {i} of 2: {name} ===", entry  # the index points at the banner...
        assert lines[b - 1] == f"=== END OF SOURCE {i} of 2 ==="  # ...and the end banner
    assert "(Cal Newport)" in "\n".join(lines[:8])

    meta = read_meta(slug)
    assert meta["kind"] == "combined" and meta["indexed"] is True  # one member is searchable
    assert [m["slug"] for m in combined.members_of(slug)] == ["deep_work", "atomic_habits"]
    assert combined.members_of("deep_work") == []  # an ordinary source has no members


def test_combined_source_is_only_searchable_when_a_member_is_and_keeps_its_file_when_unchanged():
    write_source("deep_work", WORK)
    write_source("atomic_habits", HABITS)
    short = [dict(r, indexed=0) for r in rows()]

    slug, _ = combined.prepare_combined_source(short)
    assert read_meta(slug)["indexed"] is False  # two short transcripts: read whole, no digest
    stamp = book_file(slug).stat().st_mtime_ns
    combined.prepare_combined_source(short)
    assert book_file(slug).stat().st_mtime_ns == stamp  # unchanged text is not rewritten, so its digest stays valid

    with pytest.raises(ValueError):
        combined.prepare_combined_source(short[:1])


def test_long_titles_are_shortened():
    titles = [f"A Rather Long Book Title Number {i}" for i in range(6)]
    assert combined.combined_title(titles) == "A Rather Long Book Title Number 0 + 5 more sources"


def test_one_episode_from_two_sources_end_to_end(client, monkeypatch, tmp_path, digests):
    add_ready_source(client, monkeypatch, "Deep_Work.pdf")
    add_ready_source(client, monkeypatch, "Atomic_Habits.pdf")
    write_source("deep_work", WORK)
    write_source("atomic_habits", HABITS)
    slug, title = "deep_work_+_atomic_habits", "Deep Work + Atomic Habits"

    audio = tmp_path / "podcast_audio.mp3"
    audio.write_bytes(b"ID3")

    def write_script():
        (DATA_DIR / slug / "script.md").write_text(SCRIPT, encoding="utf-8")
        return script_gate()

    content = ScriptedGraph(write_script, {"messages": []})
    production = ScriptedGraph(audio_gate(audio), lambda: {"episode_result": str(audio)})
    monkeypatch.setattr(generation, "get_content_director", lambda: content)
    monkeypatch.setattr(generation, "get_production_workflow", lambda: production)

    started = client.post("/api/generate", json={"source_slugs": ["deep_work", "atomic_habits"]})
    assert started.status_code == 202
    body = started.json()
    assert body["slug"] == slug and body["result"]["sources"] == ["deep_work", "atomic_habits"] and body["result"]["title"] == title

    await_gate(client, body["id"], "script")
    assert digests == [title]  # one digest, of the combined text, under the combined title
    assert content.inputs[0]["book_title"] == title

    # either member is busy while the combined run is unfinished, and so is the same set again
    assert client.post("/api/generate", json={"source_slug": "atomic_habits"}).status_code == 409
    assert client.post("/api/generate", json={"source_slugs": ["atomic_habits", "deep_work"]}).status_code == 409

    client.post(f"/api/jobs/{body['id']}/decision", json={"approved": True})
    await_gate(client, body["id"], "audio")
    assert production.inputs[0]["book_title"] == title and production.inputs[0]["script"] == str(DATA_DIR / slug / "script.md")
    client.post(f"/api/jobs/{body['id']}/decision", json={"approved": True})
    done = wait_for(lambda: (j := job(client, body["id"]))["status"] == "done" and j)

    episode = client.get(nb_url(client, "episodes")).json()[0]
    assert episode["id"] == done["result"]["episode_id"] and episode["title"] == title

    # once it is done the sources are free again
    assert client.post("/api/generate", json={"source_slug": "atomic_habits"}).status_code != 409


def test_starting_a_run_validates_the_sources(client, monkeypatch):
    add_ready_source(client, monkeypatch, "Deep_Work.pdf")
    assert client.post("/api/generate", json={"source_slugs": []}).status_code == 422
    assert client.post("/api/generate", json={"source_slugs": ["deep_work", "nope"]}).status_code == 404
    # the same source twice is one source, so it makes an ordinary single-source run rather than a combined one
    monkeypatch.setattr(generation, "get_content_director", lambda: ScriptedGraph(script_gate()))
    started = client.post("/api/generate", json={"source_slugs": ["deep_work", "deep_work"]}).json()
    assert started["slug"] == "deep_work" and "sources" not in started["result"]


def test_retrieval_searches_every_searchable_member_and_names_the_source(monkeypatch):
    write_source("deep_work", WORK)
    write_source("atomic_habits", HABITS)
    slug, title = combined.prepare_combined_source([dict(r, indexed=1) if r["slug"] == "deep_work" else r for r in rows()])

    seen = {}
    docs = [SimpleNamespace(page_content="Focus is a skill.", metadata={"context_summary": "ctx", "Title": "Deep Work"})]

    class FakeVectors:
        def as_retriever(self, search_kwargs):
            seen.update(search_kwargs)
            return "base"

    class FakeCompression:
        def __init__(self, base_compressor, base_retriever):
            pass

        def invoke(self, query):
            return docs

    monkeypatch.setattr(shared_tools, "vector_store", FakeVectors())
    monkeypatch.setattr(shared_tools, "OpenRouterRerank", lambda top_n: None)
    monkeypatch.setattr(shared_tools, "ContextualCompressionRetriever", FakeCompression)

    out = shared_tools.SharedContentTools.retrieve_info.func("focus", SimpleNamespace(state={"book_title": title}))

    assert seen["filter"] == {"book_slug": {"$in": ["deep_work"]}}  # the short transcript has no chunks to search
    assert out == [{"Chunk content": "Focus is a skill.", "Context summary": "ctx", "Source": "Deep Work"}]
