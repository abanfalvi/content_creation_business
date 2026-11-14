import logging
import re
import shutil
import threading
import time

from langgraph.types import Command

from podcast_generation.settings import DATA_DIR, project_path

from . import db, notebooks, sources

log = logging.getLogger(__name__)

CONTENT_QUERY = "Build the expert and draft the episode"
HOST_NAME = "Jordan"  # the host's speaker label; the TTS voice map in speech_generation is keyed on it

# Files a run writes into data/<slug>/ and must not inherit from the previous run.
_RUN_ARTIFACTS = ("expert_persona.md", "planner_notes.md", "script_plan.md", "script.md")

_ACTIVITY = {
    "call_expert_builder_agent": "Building the expert profile",
    "review_expert_profile": "Reviewing the expert profile",
    "call_script_drafter_agent": "Planning and drafting the script",
    "full_flexibility": "Revising from your feedback",
    "human_review": "Preparing the script for your review",
    "get_lessons_learned": "Saving lessons from this run",
}

# The agent graphs hold a Postgres store and are built once; serialise the first build.
_build_lock = threading.Lock()


class GenerationError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def get_content_director():
    from podcast_generation.agents.content_specialists.director.agent import get_director_agent

    with _build_lock:
        return get_director_agent()


def get_production_workflow():
    from podcast_generation.agents.production_specialists.speech_generation import get_speech_gen_workflow

    with _build_lock:
        return get_speech_gen_workflow()


# --- jobs ---------------------------------------------------------------------------------

def get_job(job_id: str) -> dict | None:
    return db.one("SELECT * FROM jobs WHERE id = ?", [job_id])


def list_jobs(notebook_id: str, limit: int = 30) -> list[dict]:
    return db.query("SELECT * FROM jobs WHERE notebook_id = ? AND kind = 'generate' ORDER BY created_at DESC LIMIT ?", [notebook_id, limit])


def _set(job_id: str, **fields) -> None:
    db.update("jobs", "id", job_id, updated_at=db.now(), **fields)


def _new_job(kind: str, slug: str, notebook_id: str, **extra) -> dict:
    ts = db.now()
    job = {"id": db.new_id(), "notebook_id": notebook_id, "kind": kind, "slug": slug, "status": "running",
           "stage": "", "error": "", "created_at": ts, "updated_at": ts, **extra}
    db.insert("jobs", job)
    notebooks.touch(notebook_id)
    return get_job(job["id"])


def _active_job(kind: str, **where) -> dict | None:
    col, val = next(iter(where.items()))
    return db.one(f"SELECT * FROM jobs WHERE kind = ? AND {col} = ? AND status IN ('running', 'awaiting_approval')", [kind, val])


def recover_interrupted() -> None:
    """Jobs that were running when the server stopped cannot continue; those awaiting approval can."""
    db.execute(
        "UPDATE jobs SET status = 'failed', error = ? WHERE status = 'running'",
        ["Interrupted by a server restart. Start it again."],
    )


def describe(job: dict) -> dict:
    """The job as the API returns it: the stored row plus what it is doing right now."""
    out = dict(job)
    out["activity"] = _activity(job)
    gate = out.get("gate")
    if gate and gate.get("type") == "audio":
        out["gate"] = {**gate, "audio_url": f"/api/jobs/{job['id']}/audio"}
        out["gate"].pop("audio_path", None)
    return out


def _activity(job: dict) -> str:
    if job["status"] == "awaiting_approval":
        return "Waiting for your review"
    if job["status"] != "running":
        return ""
    if job["stage"] == "production":
        return "Producing and editing the audio"
    step = None
    # Best effort and never blocking: skip it while a worker thread is still building the graph.
    if _build_lock.acquire(blocking=False):
        try:
            from podcast_generation.agents.content_specialists.director.agent import get_director_agent

            state = get_director_agent().get_state({"configurable": {"thread_id": job["id"]}})
            step = (state.values or {}).get("active_agent")
        except Exception:  # noqa: BLE001
            step = None
        finally:
            _build_lock.release()
    return _ACTIVITY.get(step, "Working on the script")


# --- generate -------------------------------------------------------------------------------

def start_generation(slug: str) -> dict:
    src = sources.get_source(slug)
    if src is None:
        raise GenerationError("Unknown source.", 404)
    if src["status"] != "ready":
        raise GenerationError("This source has not finished processing yet.", 409)
    if _active_job("generate", slug=slug):
        raise GenerationError("An episode is already being generated from this source.", 409)
    _archive_previous_run(slug)
    return _new_job("generate", slug, src["notebook_id"], stage="content", result={"script_approved": False})


def _archive_previous_run(slug: str) -> None:
    """Move the last run's working files aside so a new run starts fresh (nothing is deleted)."""
    book_dir = DATA_DIR / slug
    old = [book_dir / name for name in _RUN_ARTIFACTS if (book_dir / name).exists()]
    if not old:
        return
    target = book_dir / "archive" / time.strftime("%Y%m%d-%H%M%S")
    target.mkdir(parents=True, exist_ok=True)
    for path in old:
        shutil.move(str(path), target / path.name)


def submit_decision(job_id: str, approved: bool, feedback: str = "") -> dict:
    job = get_job(job_id)
    if job is None:
        raise GenerationError("Unknown job.", 404)
    if job["status"] != "awaiting_approval" or not job.get("gate"):
        raise GenerationError("This job is not waiting for a decision.", 409)
    if not approved and not feedback.strip():
        raise GenerationError("Say what needs to change so the next attempt can address it.", 422)
    fields: dict = {"status": "running", "gate": None}
    if job["gate"]["type"] == "script" and approved:
        fields["result"] = {**(job.get("result") or {}), "script_approved": True}
    _set(job_id, **fields)
    return get_job(job_id)


def advance(job_id: str, decision: dict | None = None) -> None:
    """Run the job to its next human gate or to completion. Blocking: call from a worker thread."""
    try:
        _advance(get_job(job_id), decision)
    except Exception as exc:  # noqa: BLE001 - recorded on the job for the UI
        log.exception("Job %s failed", job_id)
        _set(job_id, status="failed", gate=None, error=str(exc) or type(exc).__name__)


def _advance(job: dict, decision: dict | None) -> None:
    while True:
        graph, config, first_input = _stage(job)
        outcome = graph.invoke(Command(resume=decision) if decision is not None else first_input, config=config)
        decision = None

        interrupts = outcome.get("__interrupt__")
        if interrupts:
            _set(job["id"], status="awaiting_approval", gate=_gate(job["stage"], interrupts[0].value))
            return

        if job["stage"] == "content":
            if not (job.get("result") or {}).get("script_approved"):
                raise RuntimeError("The run ended before the script was approved, so no audio was produced.")
            _set(job["id"], stage="production")
            job = get_job(job["id"])
            continue
        _finish(job, outcome)
        return


def _stage(job: dict):
    """(graph, run config, first input) for the job's current stage."""
    slug = job["slug"]
    config = {"configurable": {"thread_id": job["id"]}}
    if job["stage"] == "content":
        title = sources.get_source(slug)["title"]
        first = {"messages": [("user", CONTENT_QUERY)], "active_agent": "call_expert_builder_agent", "book_title": title}
        return get_content_director(), config, first

    script_path = DATA_DIR / slug / "script.md"
    if not script_path.exists():
        raise RuntimeError("The script file is missing, so the audio cannot be produced.")
    first = {
        "book_title": sources.get_source(slug)["title"],
        "expert_name": _expert_name(script_path.read_text(encoding="utf-8")),
        "script": str(script_path),
        "audio_result": "",
        "feedback": "",
    }
    return get_production_workflow(), config, first


def _expert_name(script: str) -> str:
    """The expert's speaker label: the first `**Name:**` in the script that is not the host."""
    for name in re.findall(r"\*\*(.+?):\*\*", script):
        if name.strip() != HOST_NAME:
            return name.strip()
    raise RuntimeError(f"The script has no speaker other than the host ({HOST_NAME}).")


def _gate(stage: str, payload: dict) -> dict:
    if stage == "content":
        description = payload["action_requests"][0]["description"]
        instructions, _, script = description.partition("\n\n---\n")
        return {"type": "script", "instructions": instructions.strip(), "script": script.strip()}
    audio = project_path(payload["audio_path"]) if payload.get("audio_path") else None
    return {
        "type": "audio",
        "message": payload.get("message", ""),
        "audio_path": str(audio) if audio else "",
        "rubric": payload.get("rubric"),
    }


def _finish(job: dict, outcome: dict) -> None:
    final = outcome.get("episode_result") or outcome.get("audio_result")
    audio = project_path(final) if final else None
    if audio is None or not audio.exists():
        raise RuntimeError("The approved audio file could not be found.")

    slug = job["slug"]
    episode_id = db.new_id()
    episodes_dir = DATA_DIR / slug / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    # Copies: the workflow reuses one audio file name per book, which a later run would overwrite.
    audio_copy = episodes_dir / f"{episode_id}{audio.suffix or '.mp3'}"
    script_copy = episodes_dir / f"{episode_id}_script.md"
    shutil.copy2(audio, audio_copy)
    shutil.copy2(DATA_DIR / slug / "script.md", script_copy)
    db.insert("episodes", {
        "id": episode_id, "notebook_id": job["notebook_id"], "slug": slug, "title": sources.get_source(slug)["title"],
        "audio_path": str(audio_copy), "script_path": str(script_copy),
        "job_id": job["id"], "created_at": db.now(),
    })
    _set(job["id"], status="done", gate=None, result={**(job.get("result") or {}), "episode_id": episode_id})


# --- episodes -------------------------------------------------------------------------------

def list_episodes(notebook_id: str) -> list[dict]:
    return db.query("SELECT * FROM episodes WHERE notebook_id = ? ORDER BY created_at DESC", [notebook_id])


def get_episode(episode_id: str) -> dict | None:
    return db.one("SELECT * FROM episodes WHERE id = ?", [episode_id])
