"""YouTube sources: link handling, transcripts, ingestion, and how QA chat and the agents read a short transcript."""
import sqlite3
from types import SimpleNamespace

import pytest
from conftest import nb_url, wait_for
from langchain_core.messages import AIMessage
from test_chat import ScriptedModel, sse_events

from podcast_generation.agents.content_specialists import shared_tools
from podcast_generation.agents.content_specialists.utils import get_book_path
from podcast_generation.agents.content_specialists.expert_builder_agent.tools import ExpertProfileTools
from podcast_generation.agents.qa_chat import tools as qa_tools
from podcast_generation.book_preprocessing import pipeline, source_meta, video
from podcast_generation.services import chat, db, generation, sources
from podcast_generation.settings import DATA_DIR

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
INFO = {"id": "dQw4w9WgXcQ", "title": "How Focus Works: A Talk", "channel": "Some Channel", "duration": 754, "is_live": False}
TRANSCRIPT = video.build_transcript(
    "How Focus Works", "Some Channel", URL, 754,
    [(0, "Focus is a skill. You train it. Distraction is the enemy."), (300, "Rest matters too. Sleep first.")],
)


# --- links, titles, text ------------------------------------------------------------------

@pytest.mark.parametrize("link", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "http://youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PL123",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?si=abc",
    "youtu.be/dQw4w9WgXcQ",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/live/dQw4w9WgXcQ",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
])
def test_video_links_are_recognised(link):
    assert video.video_id(link) == "dQw4w9WgXcQ"


@pytest.mark.parametrize("link", [
    "https://www.youtube.com/playlist?list=PL123",
    "https://www.youtube.com/@somechannel",
    "https://www.youtube.com/watch?v=short",
    "https://vimeo.com/123456789",
    "https://evil.example/watch?v=dQw4w9WgXcQ",
    "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
    "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
    "not a link",
])
def test_other_links_are_refused(link):
    assert video.video_id(link) is None


def test_titles_become_safe_folder_names():
    assert video.clean_title('What?  A "great" talk: part 1/2 | Live...') == "What A great talk: part 1 2 Live"
    assert video.clean_title("x" * 300) == "x" * 100


def test_cuts_land_in_pauses_near_each_target_and_short_audio_is_not_cut():
    assert video.choose_cuts([], 340) == []
    assert video.choose_cuts([], 700) == [300.0, 600.0]  # no pauses: cut at the targets
    assert video.choose_cuts([290.0, 320.0, 610.0], 700) == [290.0, 610.0]  # the pause nearest each target
    assert video.choose_cuts([100.0], 700) == [300.0, 600.0]  # a pause too far from a target is ignored


def test_paragraphs_group_sentences_and_cut_unpunctuated_runs():
    text = " ".join(f"This is sentence number {i} of the talk." for i in range(40))
    paras = video.paragraphs(text)
    assert len(paras) > 1 and all(len(p.split()) < 130 for p in paras)
    assert " ".join(paras) == text
    run = " ".join(["word"] * 500)
    assert [len(p.split()) for p in video.paragraphs(run)] == [180, 180, 140]


def test_a_transcript_round_trips_with_a_stamp_on_every_part():
    assert TRANSCRIPT.startswith("# How Focus Works\n")
    assert "Source: YouTube video by Some Channel" in TRANSCRIPT and "Duration: 12:34" in TRANSCRIPT
    passages = video.split_transcript(TRANSCRIPT)
    assert passages == [("00:00", "Focus is a skill. You train it. Distraction is the enemy."), ("05:00", "Rest matters too. Sleep first.")]
    assert video.clock(3725) == "1:02:05"


# --- adding a video -------------------------------------------------------------------------

def fake_ingest(monkeypatch, words: int = 100, calls=None):
    """Stand in for the audio download and transcription: write a transcript of `words` words and its facts."""
    async def fake(title, url, channel="", duration=0, on_stage=lambda s: None):
        if calls is not None:
            calls.append((title, url, channel, duration))
        on_stage("Transcribing the audio")
        slug = get_book_path(title)
        text = video.build_transcript(title, channel, url, duration, [(0, " ".join(["word."] * words))])
        source_meta.book_file(slug).parent.mkdir(parents=True, exist_ok=True)
        source_meta.book_file(slug).write_text(text, encoding="utf-8")
        source_meta.write_meta(slug, kind="youtube", title=title, indexed=words > source_meta.FULL_TEXT_MAX_WORDS)
        return "ok"

    monkeypatch.setattr(sources, "preprocess_video", fake)
    monkeypatch.setattr(sources.video, "fetch_video_info", lambda url: dict(INFO))


def add_video(client, url=URL):
    return client.post(nb_url(client, "sources/youtube"), json={"url": url})


def test_adding_a_video_registers_it_and_ingests_it_in_the_background(client, monkeypatch):
    calls = []
    fake_ingest(monkeypatch, calls=calls)

    res = add_video(client, "https://youtu.be/dQw4w9WgXcQ?t=5")
    assert res.status_code == 202
    source = res.json()
    assert (source["kind"], source["title"], source["slug"]) == ("youtube", "How Focus Works: A Talk", "how_focus_works_a_talk")
    assert (source["author"], source["duration"], source["pages"]) == ("Some Channel", 754, 0)

    ready = wait_for(lambda: next((s for s in client.get(nb_url(client, "sources")).json() if s["status"] == "ready"), None))
    assert calls == [("How Focus Works: A Talk", URL, "Some Channel", 754)]  # the link is stored in its canonical form
    assert ready["indexed"] == 0  # 100 words: read whole, no chunks


def test_a_long_transcript_is_marked_indexed(client, monkeypatch):
    fake_ingest(monkeypatch, words=source_meta.FULL_TEXT_MAX_WORDS + 1000)
    add_video(client)
    assert wait_for(lambda: next((s for s in client.get(nb_url(client, "sources")).json() if s["status"] == "ready"), None))["indexed"] == 1


def test_bad_videos_are_refused_with_a_reason(client, monkeypatch):
    fake_ingest(monkeypatch)
    assert "not a link to a single YouTube video" in add_video(client, "https://vimeo.com/1").json()["detail"]

    monkeypatch.setattr(sources.video, "fetch_video_info", lambda url: {**INFO, "is_live": True})
    assert "live stream" in add_video(client).json()["detail"]

    monkeypatch.setattr(sources.video, "fetch_video_info", lambda url: {**INFO, "duration": 9 * 3600})
    assert "limit is 8 hours" in add_video(client).json()["detail"]

    def private(url):
        raise video.VideoError("Private video")

    monkeypatch.setattr(sources.video, "fetch_video_info", private)
    res = add_video(client)
    assert res.status_code == 400 and "Private video" in res.json()["detail"]
    assert client.get(nb_url(client, "sources")).json() == []


def test_the_same_video_cannot_be_added_twice_and_removing_it_clears_its_facts(client, monkeypatch):
    fake_ingest(monkeypatch)
    add_video(client)
    wait_for(lambda: client.get(nb_url(client, "sources")).json()[0]["status"] == "ready")
    assert add_video(client).status_code == 409

    slug = "how_focus_works_a_talk"
    assert source_meta.meta_file(slug).exists()
    assert client.delete(f"/api/sources/{slug}").status_code == 204
    assert not source_meta.meta_file(slug).exists()  # a later source with this slug must not inherit `indexed: false`
    assert source_meta.is_indexed(slug)


# --- ingestion --------------------------------------------------------------------------------

def run_pipeline(monkeypatch, tmp_path, words: int, title="Pipeline Talk"):
    events = {"indexed": [], "deleted": [], "transcribed": 0}

    def fake_download(url, out_dir):
        return tmp_path / "audio.mp3"

    async def fake_transcribe(audio, work_dir, title, channel, url, duration, on_progress=None):
        events["transcribed"] += 1
        return video.build_transcript(title, channel, url, duration, [(0, " ".join(["word."] * words))])

    async def fake_index(md_path, title, author, on_stage):
        events["indexed"].append((title, author))

    monkeypatch.setattr(pipeline, "download_audio", fake_download)
    monkeypatch.setattr(pipeline, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(pipeline, "_index", fake_index)
    monkeypatch.setattr(pipeline, "delete_book_vectors", lambda slug: events["deleted"].append(slug))

    import asyncio

    asyncio.run(pipeline.preprocess_video(title, URL, "Chan", 60))
    return events


def test_a_short_transcript_is_not_chunked_or_embedded(monkeypatch, tmp_path):
    events = run_pipeline(monkeypatch, tmp_path, words=500)
    assert events["indexed"] == [] and events["deleted"] == ["pipeline_talk"]
    meta = source_meta.read_meta("pipeline_talk")
    assert (meta["kind"], meta["indexed"], meta["video_id"], meta["title"]) == ("youtube", False, "dQw4w9WgXcQ", "Pipeline Talk")
    assert not source_meta.is_indexed("pipeline_talk")


def test_a_transcript_over_the_limit_goes_through_the_chunking_every_book_gets(monkeypatch, tmp_path):
    events = run_pipeline(monkeypatch, tmp_path, words=source_meta.FULL_TEXT_MAX_WORDS + 1, title="Long Talk")
    assert events["indexed"] == [("Long Talk", "Chan")] and events["deleted"] == []
    assert source_meta.is_indexed("long_talk")


def test_the_limit_is_on_words_not_on_the_header(monkeypatch, tmp_path):
    events = run_pipeline(monkeypatch, tmp_path, words=source_meta.FULL_TEXT_MAX_WORDS - 100, title="Edge Talk")
    assert events["indexed"] == []


def test_a_transcript_already_made_for_the_same_video_is_reused_but_not_for_another(monkeypatch, tmp_path):
    first = run_pipeline(monkeypatch, tmp_path, words=300, title="Reuse Talk")
    assert first["transcribed"] == 1
    again = run_pipeline(monkeypatch, tmp_path, words=300, title="Reuse Talk")
    assert again["transcribed"] == 0  # the same video: the transcript on disk is kept

    source_meta.write_meta("reuse_talk", kind="youtube", video_id="someoneelse1", indexed=False)
    other = run_pipeline(monkeypatch, tmp_path, words=300, title="Reuse Talk")
    assert other["transcribed"] == 1  # another video under this slug: transcribed afresh


# --- QA chat -----------------------------------------------------------------------------------

def write_short_source(slug="how_focus_works_a_talk"):
    source_meta.book_file(slug).parent.mkdir(parents=True, exist_ok=True)
    source_meta.book_file(slug).write_text(TRANSCRIPT, encoding="utf-8")
    source_meta.write_meta(slug, kind="youtube", title="How Focus Works: A Talk", indexed=False)


def ask(client, monkeypatch, *messages, question="What is focus?"):
    fake_ingest(monkeypatch)
    add_video(client)
    wait_for(lambda: client.get(nb_url(client, "sources")).json()[0]["status"] == "ready")
    write_short_source()
    monkeypatch.setattr(chat, "build_chat_model", lambda: ScriptedModel(script=list(messages)))
    session = client.post(nb_url(client, "chat/sessions")).json()["id"]
    res = client.post(f"/api/chat/sessions/{session}/messages", json={"message": question, "source_slugs": ["how_focus_works_a_talk"]})
    return sse_events(res)


READ = AIMessage(content="", tool_calls=[{"name": "read_full_source", "args": {"slug": "how_focus_works_a_talk"}, "id": "c1"}])
SEARCH = AIMessage(content="", tool_calls=[{"name": "semantic_search_sources", "args": {"query": "focus"}, "id": "c1"}])


def test_a_short_source_is_read_whole_and_its_passages_can_be_cited(client, monkeypatch):
    ref = qa_tools._ref("how_focus_works_a_talk", 1, "chunk")
    events = ask(client, monkeypatch, READ, AIMessage(content=f"Focus is trainable [[{ref}]]."))
    assert events[-1] == {"type": "done"}
    cited = [e for e in events if e["type"] == "sources" and e["sources"]][-1]["sources"]
    assert [(c["ref"], c["chapter"]) for c in cited] == [(ref, "from 00:00")]
    assert "Focus is a skill" in cited[0]["text"] and cited[0]["title"] == "How Focus Works: A Talk"


def test_searching_a_short_source_says_to_read_it_whole_and_searches_nothing(client, monkeypatch):
    searched = []
    monkeypatch.setattr(qa_tools, "_search_chunks", lambda *a, **k: searched.append(a) or ([], []))
    seen_by_model = []

    class Spy(ScriptedModel):
        def _generate(self, messages, *a, **k):
            seen_by_model.append(messages[-1].content)
            return super()._generate(messages, *a, **k)

    fake_ingest(monkeypatch)
    add_video(client)
    wait_for(lambda: client.get(nb_url(client, "sources")).json()[0]["status"] == "ready")
    write_short_source()
    monkeypatch.setattr(chat, "build_chat_model", lambda: Spy(script=[SEARCH, AIMessage(content="ok")]))
    session = client.post(nb_url(client, "chat/sessions")).json()["id"]
    client.post(f"/api/chat/sessions/{session}/messages", json={"message": "q", "source_slugs": ["how_focus_works_a_talk"]})

    assert searched == []
    assert "no search index" in seen_by_model[-1] and "read_full_source" in seen_by_model[-1] and "'how_focus_works_a_talk'" in seen_by_model[-1]


def test_a_source_is_read_in_full_only_once_per_conversation(client, monkeypatch):
    second = AIMessage(content="", tool_calls=[{"name": "read_full_source", "args": {"slug": "how_focus_works_a_talk"}, "id": "c2"}])
    seen_by_model = []

    class Spy(ScriptedModel):
        def _generate(self, messages, *a, **k):
            seen_by_model.append(messages[-1].content)
            return super()._generate(messages, *a, **k)

    fake_ingest(monkeypatch)
    add_video(client)
    wait_for(lambda: client.get(nb_url(client, "sources")).json()[0]["status"] == "ready")
    write_short_source()
    monkeypatch.setattr(chat, "build_chat_model", lambda: Spy(script=[READ, second, AIMessage(content="done")]))
    session = client.post(nb_url(client, "chat/sessions")).json()["id"]
    client.post(f"/api/chat/sessions/{session}/messages", json={"message": "q", "source_slugs": ["how_focus_works_a_talk"]})
    assert "Full transcript of How Focus Works: A Talk (2 passages)" in seen_by_model[1]
    assert "already read in full" in seen_by_model[2]


def test_only_a_selected_unindexed_source_can_be_read_in_full(client, monkeypatch):
    other = AIMessage(content="", tool_calls=[{"name": "read_full_source", "args": {"slug": "deep_work"}, "id": "c1"}])
    events = ask(client, monkeypatch, other, AIMessage(content="No."))
    assert events[-1] == {"type": "done"}  # refused inside the tool, not an error that ends the turn


# --- the content agents ----------------------------------------------------------------------

def runtime(title="How Focus Works: A Talk"):
    return SimpleNamespace(state={"book_title": title})


def test_the_expert_builder_gets_the_whole_numbered_transcript_instead_of_a_digest(client, monkeypatch):
    write_short_source()
    text = ExpertProfileTools.read_book_digest.func(runtime())
    assert "no digest" in text and "1\t# How Focus Works" in text and "Focus is a skill" in text


def test_the_expert_builder_still_gets_a_missing_digest_message_for_an_indexed_book():
    book = DATA_DIR / "indexed_book"
    book.mkdir(parents=True, exist_ok=True)
    (book / "book_content.md").write_text("text", encoding="utf-8")
    assert "No digest exists" in ExpertProfileTools.read_book_digest.func(runtime("Indexed Book"))


def test_retrieve_info_says_there_is_nothing_to_search_instead_of_returning_nothing():
    write_short_source()
    message = shared_tools.SharedContentTools.retrieve_info.func("focus", runtime())
    assert isinstance(message, str) and "no search index" in message and "how_focus_works_a_talk" in message


def test_no_digest_is_built_for_a_short_transcript(client, monkeypatch):
    built = []

    async def fake_digest(title, force=False):
        built.append(title)
        return "ok"

    monkeypatch.setattr(generation, "digest_book", fake_digest)
    fake_ingest(monkeypatch)
    add_video(client)
    wait_for(lambda: client.get(nb_url(client, "sources")).json()[0]["status"] == "ready")
    job = {"id": "j1", "slug": "how_focus_works_a_talk", "stage": "content"}

    generation._ensure_digest(job)
    assert built == []

    db.update("sources", "slug", "how_focus_works_a_talk", indexed=1)
    generation._ensure_digest(job)
    assert built == ["How Focus Works: A Talk"]


# --- the database ------------------------------------------------------------------------------

def test_a_database_from_before_videos_gets_the_new_columns_and_its_books_stay_indexed_pdfs(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE sources (slug TEXT PRIMARY KEY, notebook_id TEXT, title TEXT NOT NULL, filename TEXT NOT NULL,"
        " pdf_path TEXT NOT NULL, pages INTEGER NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '',"
        " error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL);"
        "INSERT INTO sources VALUES ('deep_work', 'nb', 'Deep Work', 'Deep_Work.pdf', 'x.pdf', 300, 'ready', '', '', 1.0);"
    )
    old.commit()
    old.close()

    db.init(path)
    row = db.one("SELECT * FROM sources WHERE slug = 'deep_work'")
    assert (row["kind"], row["url"], row["author"], row["duration"], row["indexed"]) == ("pdf", "", "", 0, 1)
    db.init(path)  # running it again is harmless
