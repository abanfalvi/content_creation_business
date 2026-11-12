"""The generate -> approve script -> approve audio -> publish flow, with scripted stand-ins for the agent graphs."""
from types import SimpleNamespace

from conftest import make_pdf, wait_for
from langgraph.types import Command

from podcast_generation.services import generation, sources
from podcast_generation.settings import DATA_DIR

SCRIPT = "**Jordan:** Welcome back.\n\n**Dr. Sam:** Glad to be here.\n"


class Interrupt:
    def __init__(self, value):
        self.value = value


def script_gate(text=SCRIPT):
    return {"__interrupt__": [Interrupt({"action_requests": [{"description": f"Review the script.\n\n---\n{text}"}]})]}


def audio_gate(path):
    return {"__interrupt__": [Interrupt({"message": "Review the episode.", "audio_path": str(path), "rubric": {"transitions": 4}})]}


class ScriptedGraph:
    """invoke() returns the next scripted outcome (calling it first if it is a function); records its inputs."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.inputs = []

    def invoke(self, value, config=None):
        self.inputs.append(value)
        step = self.steps.pop(0)
        return step() if callable(step) else step

    def get_state(self, config):
        return SimpleNamespace(values={"active_agent": "call_script_drafter_agent"})


def add_ready_source(client, monkeypatch, name="Deep_Work.pdf"):
    async def fake(*a, **k):
        return "ok"

    monkeypatch.setattr(sources, "preprocess_book", fake)
    client.post("/api/sources", files=[("files", (name, make_pdf(), "application/pdf"))])
    wait_for(lambda: all(s["status"] == "ready" for s in client.get("/api/sources").json()))


def job(client, job_id):
    return client.get(f"/api/jobs/{job_id}").json()


def await_gate(client, job_id, kind):
    return wait_for(lambda: (j := job(client, job_id))["status"] == "awaiting_approval" and j["gate"]["type"] == kind and j)


def test_full_flow_with_a_rejected_script_and_a_rejected_audio(client, monkeypatch, tmp_path):
    add_ready_source(client, monkeypatch)
    book_dir = DATA_DIR / "deep_work"
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "script.md").write_text("OLD RUN", encoding="utf-8")  # must be archived, not reused

    def write_script():
        (book_dir / "script.md").write_text(SCRIPT, encoding="utf-8")
        return script_gate()

    audio = tmp_path / "podcast_audio.mp3"
    audio.write_bytes(b"ID3-first-take")

    content = ScriptedGraph(write_script, script_gate("**Jordan:** v2\n**Dr. Sam:** v2"), {"messages": []})
    production = ScriptedGraph(audio_gate(audio), lambda: audio_gate(audio), lambda: {"episode_result": str(audio)})
    monkeypatch.setattr(generation, "get_content_director", lambda: content)
    monkeypatch.setattr(generation, "get_production_workflow", lambda: production)

    started = client.post("/api/generate", json={"source_slug": "deep_work"})
    assert started.status_code == 202
    job_id = started.json()["id"]
    assert list((book_dir / "archive").glob("*/script.md"))[0].read_text(encoding="utf-8") == "OLD RUN"

    # 1. script gate: rejecting needs feedback
    gate = await_gate(client, job_id, "script")["gate"]
    assert "Welcome back" in gate["script"]
    assert client.post(f"/api/jobs/{job_id}/decision", json={"approved": False}).status_code == 422
    client.post(f"/api/jobs/{job_id}/decision", json={"approved": False, "feedback": "Shorter intro"})
    wait_for(lambda: len(content.inputs) > 1)  # the resume runs in the background
    assert content.inputs[1] == Command(resume={"approved": False, "feedback": "Shorter intro"})

    # 2. revised script gate -> approve -> production starts
    await_gate(client, job_id, "script")
    client.post(f"/api/jobs/{job_id}/decision", json={"approved": True})
    gate = await_gate(client, job_id, "audio")["gate"]
    assert production.inputs[0]["expert_name"] == "Dr. Sam"
    assert gate["rubric"] == {"transitions": 4} and gate["audio_url"] == f"/api/jobs/{job_id}/audio"
    assert client.get(gate["audio_url"]).content == b"ID3-first-take"

    # 3. audio gate: reject, then approve
    client.post(f"/api/jobs/{job_id}/decision", json={"approved": False, "feedback": "Too quiet"})
    await_gate(client, job_id, "audio")
    audio.write_bytes(b"ID3-final")
    client.post(f"/api/jobs/{job_id}/decision", json={"approved": True})

    done = wait_for(lambda: (j := job(client, job_id))["status"] == "done" and j)
    episode = client.get("/api/episodes").json()[0]
    assert done["result"]["episode_id"] == episode["id"] and episode["title"] == "Deep Work"
    assert client.get(episode["audio_url"]).content == b"ID3-final"

    # a new run on the same source is allowed again once the first is finished
    content.steps, production.steps = [script_gate(), {"messages": []}], []
    assert client.post("/api/generate", json={"source_slug": "deep_work"}).status_code == 202


def test_cannot_start_two_runs_for_one_source_or_an_unready_source(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    content = ScriptedGraph(script_gate())
    monkeypatch.setattr(generation, "get_content_director", lambda: content)

    assert client.post("/api/generate", json={"source_slug": "missing"}).status_code == 404
    first = client.post("/api/generate", json={"source_slug": "deep_work"})
    assert first.status_code == 202
    await_gate(client, first.json()["id"], "script")
    assert client.post("/api/generate", json={"source_slug": "deep_work"}).status_code == 409


def test_a_run_that_skips_the_script_approval_never_reaches_production(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    content = ScriptedGraph({"messages": []})  # the director "finishes" without ever asking for approval
    production = ScriptedGraph()
    monkeypatch.setattr(generation, "get_content_director", lambda: content)
    monkeypatch.setattr(generation, "get_production_workflow", lambda: production)

    job_id = client.post("/api/generate", json={"source_slug": "deep_work"}).json()["id"]
    failed = wait_for(lambda: (j := job(client, job_id))["status"] == "failed" and j)
    assert "before the script was approved" in failed["error"]
    assert production.inputs == []


def test_agent_errors_fail_the_job_with_a_message(client, monkeypatch):
    add_ready_source(client, monkeypatch)

    def explode():
        raise RuntimeError("POSTGRES_URI is not set.")

    monkeypatch.setattr(generation, "get_content_director", explode)
    job_id = client.post("/api/generate", json={"source_slug": "deep_work"}).json()["id"]
    failed = wait_for(lambda: (j := job(client, job_id))["status"] == "failed" and j)
    assert failed["error"] == "POSTGRES_URI is not set."


def test_publish_an_episode(client, monkeypatch, tmp_path):
    from podcast_generation.services import db

    audio, script = tmp_path / "e.mp3", tmp_path / "e_script.md"
    audio.write_bytes(b"audio")
    script.write_text(SCRIPT, encoding="utf-8")
    db.insert("episodes", {"id": "ep1", "slug": "deep_work", "title": "Deep Work", "audio_path": str(audio),
                           "script_path": str(script), "job_id": "j", "created_at": db.now()})

    seen = {}

    class Director:
        async def ainvoke(self, value, config=None):
            seen["input"] = value
            return {"messages": [SimpleNamespace(content="Scheduled for Friday 9:00.")]}

    monkeypatch.setattr(generation, "get_distribution_director", lambda: Director())

    response = client.post("/api/episodes/ep1/publish")
    assert response.status_code == 202
    done = wait_for(lambda: (j := job(client, response.json()["id"]))["status"] == "done" and j)
    assert done["result"]["message"] == "Scheduled for Friday 9:00."
    assert seen["input"]["script_path"] == str(script)

    episode = client.get("/api/episodes").json()[0]
    assert episode["published_at"] and episode["publish_result"] == "Scheduled for Friday 9:00."
    assert client.post("/api/episodes/ep1/publish").status_code == 409
    assert client.post("/api/episodes/nope/publish").status_code == 404
