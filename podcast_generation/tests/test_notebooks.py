"""Notebooks: listing, renaming, keeping each notebook's sources/chats/episodes apart, and migrating old data."""
import sqlite3
import time

from conftest import make_pdf, nb_url, wait_for

from podcast_generation.services import db, sources


def make_notebook(client, title=None):
    return client.post("/api/notebooks", json={"title": title} if title else None).json()


def upload(client, notebook_id, name="Deep_Work.pdf"):
    return client.post(
        f"/api/notebooks/{notebook_id}/sources", files=[("files", (name, make_pdf(), "application/pdf"))]
    )


def fake_ingest(monkeypatch):
    async def fake(*a, **k):
        return "ok"

    monkeypatch.setattr(sources, "preprocess_book", fake)


# --- the notebook list -------------------------------------------------------------------------

def test_notebooks_are_created_listed_and_fetched(client):
    untitled = make_notebook(client)
    named = make_notebook(client, "  Stoicism  ")  # surrounding spaces are dropped
    assert untitled["title"] == "Untitled notebook"
    assert named["title"] == "Stoicism"
    assert (named["source_count"], named["chat_count"], named["episode_count"]) == (0, 0, 0)

    listed = client.get("/api/notebooks").json()
    assert {n["id"] for n in listed} == {client.nb, untitled["id"], named["id"]}
    assert client.get(f"/api/notebooks/{named['id']}").json()["title"] == "Stoicism"
    assert client.get("/api/notebooks/nope").status_code == 404


def test_the_list_shows_what_each_notebook_holds_and_the_latest_first(client, monkeypatch):
    fake_ingest(monkeypatch)
    other = make_notebook(client, "Second")
    assert client.get("/api/notebooks").json()[0]["id"] == other["id"]  # newest first

    time.sleep(0.05)  # the clock can be coarse; make sure each use gets a distinct timestamp
    upload(client, client.nb)
    client.post(nb_url(client, "chat/sessions"))
    client.post(nb_url(client, "chat/sessions"))

    by_id = {n["id"]: n for n in client.get("/api/notebooks").json()}
    assert (by_id[client.nb]["source_count"], by_id[client.nb]["chat_count"]) == (1, 2)
    assert (by_id[other["id"]]["source_count"], by_id[other["id"]]["chat_count"]) == (0, 0)

    # using a notebook moves it to the top of the home page
    assert client.get("/api/notebooks").json()[0]["id"] == client.nb
    time.sleep(0.05)
    client.post(f"/api/notebooks/{other['id']}/chat/sessions")
    assert client.get("/api/notebooks").json()[0]["id"] == other["id"]


def test_rename_a_notebook(client):
    renamed = client.patch(f"/api/notebooks/{client.nb}", json={"title": "  Deep Work notes "})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Deep Work notes"
    assert client.get(f"/api/notebooks/{client.nb}").json()["title"] == "Deep Work notes"

    assert client.patch(f"/api/notebooks/{client.nb}", json={"title": "   "}).status_code == 422
    assert client.patch(f"/api/notebooks/{client.nb}", json={"title": "x" * 121}).status_code == 422
    assert client.patch("/api/notebooks/nope", json={"title": "Anything"}).status_code == 404
    assert client.get(f"/api/notebooks/{client.nb}").json()["title"] == "Deep Work notes"


# --- notebooks keep their contents apart --------------------------------------------------------

def test_sources_belong_to_one_notebook(client, monkeypatch):
    fake_ingest(monkeypatch)
    other = make_notebook(client, "Other")["id"]
    assert upload(client, client.nb).json()[0]["error"] is None

    assert len(client.get(nb_url(client, "sources")).json()) == 1
    assert client.get(f"/api/notebooks/{other}/sources").json() == []

    # the same book cannot be added to a second notebook; the message says where it is
    error = upload(client, other).json()[0]["error"]
    assert "already in the notebook 'Test notebook'" in error
    assert upload(client, "nope").status_code == 404


def test_chats_and_episodes_are_listed_per_notebook(client):
    other = make_notebook(client, "Other")["id"]
    client.post(nb_url(client, "chat/sessions"))
    assert len(client.get(nb_url(client, "chat/sessions")).json()) == 1
    assert client.get(f"/api/notebooks/{other}/chat/sessions").json() == []
    assert client.get(f"/api/notebooks/{other}/jobs").json() == []
    assert client.get(f"/api/notebooks/{other}/episodes").json() == []
    assert client.get("/api/notebooks/nope/chat/sessions").status_code == 404
    assert client.post("/api/notebooks/nope/chat/sessions").status_code == 404


def test_a_chat_can_only_ask_about_its_own_notebooks_sources(client, monkeypatch):
    fake_ingest(monkeypatch)
    other = make_notebook(client, "Other")["id"]
    upload(client, client.nb)
    wait_for(lambda: client.get(nb_url(client, "sources")).json()[0]["status"] == "ready")

    session = client.post(f"/api/notebooks/{other}/chat/sessions").json()
    response = client.post(
        f"/api/chat/sessions/{session['id']}/messages", json={"message": "Hi", "source_slugs": ["deep_work"]}
    )
    assert response.status_code == 422  # deep_work is ready, but it is not in this chat's notebook


# --- renaming a chat ---------------------------------------------------------------------------

def test_rename_a_chat(client):
    session = client.post(nb_url(client, "chat/sessions")).json()
    renamed = client.patch(f"/api/chat/sessions/{session['id']}", json={"title": " Focus ideas "})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Focus ideas"
    assert client.get(nb_url(client, "chat/sessions")).json()[0]["title"] == "Focus ideas"

    assert client.patch(f"/api/chat/sessions/{session['id']}", json={"title": ""}).status_code == 422
    assert client.patch("/api/chat/sessions/nope", json={"title": "Anything"}).status_code == 404


def test_a_renamed_chat_keeps_its_name_after_the_first_message(client, monkeypatch):
    from test_chat import ANSWER, add_ready_source, sse_events, use_model

    add_ready_source(client, monkeypatch)
    use_model(monkeypatch, ANSWER)
    session = client.post(nb_url(client, "chat/sessions")).json()
    client.patch(f"/api/chat/sessions/{session['id']}", json={"title": "My research"})

    sse_events(client.post(
        f"/api/chat/sessions/{session['id']}/messages", json={"message": "How do I focus?", "source_slugs": ["deep_work"]}
    ))
    assert client.get(nb_url(client, "chat/sessions")).json()[0]["title"] == "My research"


# --- deleting a notebook -----------------------------------------------------------------------

def add_episode(client, notebook_id, tmp_path, name):
    audio, script = tmp_path / f"{name}.mp3", tmp_path / f"{name}_script.md"
    audio.write_bytes(b"audio")
    script.write_text("script", encoding="utf-8")
    db.insert("episodes", {"id": name, "notebook_id": notebook_id, "slug": "deep_work", "title": "Deep Work",
                           "audio_path": str(audio), "script_path": str(script), "job_id": "j", "created_at": db.now()})
    return audio, script


def add_job(notebook_id, job_id, status):
    db.insert("jobs", {"id": job_id, "notebook_id": notebook_id, "kind": "generate", "slug": "deep_work",
                       "status": status, "stage": "content", "error": "", "created_at": db.now(), "updated_at": db.now()})


def test_deleting_a_notebook_removes_its_contents_and_leaves_the_others(client, monkeypatch, tmp_path):
    from podcast_generation.settings import UPLOAD_DIR

    fake_ingest(monkeypatch)
    keep = make_notebook(client, "Keep me")["id"]
    upload(client, client.nb)
    wait_for(lambda: client.get(nb_url(client, "sources")).json()[0]["status"] == "ready")
    pdf = UPLOAD_DIR / "deep_work.pdf"
    assert pdf.exists()
    client.post(nb_url(client, "chat/sessions"))
    audio, script = add_episode(client, client.nb, tmp_path, "gone")
    add_job(client.nb, "waiting", "awaiting_approval")  # a job waiting for a decision does not block deleting
    add_job(client.nb, "finished", "done")
    kept_audio, _ = add_episode(client, keep, tmp_path, "kept")
    client.post(f"/api/notebooks/{keep}/chat/sessions")

    assert client.delete(f"/api/notebooks/{client.nb}").status_code == 204

    assert client.get(f"/api/notebooks/{client.nb}").status_code == 404
    assert [n["id"] for n in client.get("/api/notebooks").json()] == [keep]
    for table in ("sources", "sessions", "jobs", "episodes"):
        assert db.query(f"SELECT * FROM {table} WHERE notebook_id = ?", [client.nb]) == [], table
    assert not pdf.exists() and not audio.exists() and not script.exists()

    # the other notebook is untouched
    kept = client.get(f"/api/notebooks/{keep}").json()
    assert (kept["chat_count"], kept["episode_count"]) == (1, 1)
    assert kept_audio.exists()

    # the same book can be added again, now to the other notebook
    assert upload(client, keep).json()[0]["error"] is None


def test_a_notebook_that_is_busy_cannot_be_deleted(client):
    db.insert("sources", {"slug": "busy_book", "notebook_id": client.nb, "title": "Busy", "filename": "b.pdf",
                          "pdf_path": "b.pdf", "pages": 1, "status": "processing", "stage": "", "error": "",
                          "created_at": db.now()})
    refused = client.delete(f"/api/notebooks/{client.nb}")
    assert refused.status_code == 409 and "still being processed" in refused.json()["detail"]

    db.update("sources", "slug", "busy_book", status="ready")
    add_job(client.nb, "running_job", "running")
    refused = client.delete(f"/api/notebooks/{client.nb}")
    assert refused.status_code == 409 and "still being made" in refused.json()["detail"]

    assert client.get(f"/api/notebooks/{client.nb}").status_code == 200  # nothing was removed
    assert len(db.query("SELECT * FROM sources WHERE notebook_id = ?", [client.nb])) == 1

    db.update("jobs", "id", "running_job", status="failed")
    db.execute("DELETE FROM sources WHERE slug = 'busy_book'")  # no vector entries or PDF exist for this fake row
    assert client.delete(f"/api/notebooks/{client.nb}").status_code == 204


def test_deleting_an_unknown_notebook_is_a_404(client):
    assert client.delete("/api/notebooks/nope").status_code == 404


# --- databases from before notebooks existed ----------------------------------------------------

OLD_SCHEMA = """
CREATE TABLE sources (slug TEXT PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL, pdf_path TEXT NOT NULL,
    pages INTEGER NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL);
CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, slug TEXT NOT NULL, episode_id TEXT, status TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '', gate TEXT, result TEXT, error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
    updated_at REAL NOT NULL);
CREATE TABLE episodes (id TEXT PRIMARY KEY, slug TEXT NOT NULL, title TEXT NOT NULL, audio_path TEXT NOT NULL,
    script_path TEXT NOT NULL, job_id TEXT NOT NULL, created_at REAL NOT NULL, published_at REAL, publish_result TEXT);
INSERT INTO sources VALUES ('deep_work', 'Deep Work', 'Deep_Work.pdf', 'x.pdf', 3, 'ready', '', '', 1);
INSERT INTO sessions VALUES ('s1', 'A chat', 1, 1);
INSERT INTO jobs VALUES ('j1', 'generate', 'deep_work', NULL, 'done', 'production', NULL, NULL, '', 1, 1);
INSERT INTO jobs VALUES ('j2', 'generate', 'deleted_book', NULL, 'failed', 'content', NULL, NULL, 'x', 1, 1);
INSERT INTO episodes VALUES ('e1', 'deep_work', 'Deep Work', 'a.mp3', 's.md', 'j1', 1, NULL, NULL);
"""


def test_an_old_database_is_moved_into_one_default_notebook(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.commit()
    conn.close()

    try:
        db.init(path)
        [notebook] = db.query("SELECT * FROM notebooks")
        assert notebook["title"] == "My notebook"
        for table in ("sources", "sessions", "jobs", "episodes"):
            owners = {r["notebook_id"] for r in db.query(f"SELECT notebook_id FROM {table}")}
            assert owners == {notebook["id"]}, table

        # opening it again changes nothing, and no second notebook appears
        db.init(path)
        assert len(db.query("SELECT * FROM notebooks")) == 1
    finally:
        db.init(tmp_path / "scratch.db")  # leave the shared connection on a throwaway file


def test_a_new_database_starts_without_notebooks(tmp_path):
    try:
        db.init(tmp_path / "fresh.db")
        assert db.query("SELECT * FROM notebooks") == []
    finally:
        db.init(tmp_path / "scratch.db")
