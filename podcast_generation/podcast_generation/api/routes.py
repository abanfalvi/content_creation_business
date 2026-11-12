"""HTTP routes. Thin: validation and wiring only; the logic lives in `services`."""
import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from podcast_generation.services import chat, generation, sources

router = APIRouter(prefix="/api")

# Background work started by a request. Tasks are only weakly referenced by the loop, so hold them here.
_tasks: set[asyncio.Task] = set()


def spawn(coro: Awaitable) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def in_thread(fn: Callable, *args) -> Awaitable:
    return asyncio.to_thread(fn, *args)


@router.get("/health")
def health():
    return {"status": "ok"}


# --- sources ---------------------------------------------------------------------------------

@router.get("/sources")
def list_sources():
    return sources.list_sources()


@router.post("/sources")
async def upload_sources(files: list[UploadFile]):
    """Add one or more PDFs. Each is validated now and preprocessed in the background."""
    if not files:
        raise HTTPException(400, "No files were uploaded.")
    results = []
    for upload in files:
        name = upload.filename or "upload.pdf"
        try:
            source = sources.create_source(name, await upload.read())
        except sources.SourceError as exc:
            results.append({"filename": name, "source": None, "error": str(exc)})
            continue
        spawn(in_thread(sources.ingest, source["slug"]))
        results.append({"filename": name, "source": source, "error": None})
    return results


@router.delete("/sources/{slug}", status_code=204)
def delete_source(slug: str):
    sources.delete_source(slug)


# --- chat ------------------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    source_slugs: list[str] = []


def _engine(request: Request) -> chat.ChatEngine:
    return request.app.state.chat


@router.get("/chat/sessions")
def list_sessions():
    return chat.list_sessions()


@router.post("/chat/sessions", status_code=201)
def create_session():
    return chat.create_session()


@router.delete("/chat/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request):
    if chat.get_session(session_id) is None:
        raise HTTPException(404, "No such chat.")
    await _engine(request).delete_thread(session_id)
    chat.delete_session_row(session_id)


@router.get("/chat/sessions/{session_id}/messages")
async def session_messages(session_id: str, request: Request):
    if chat.get_session(session_id) is None:
        raise HTTPException(404, "No such chat.")
    return await _engine(request).history(session_id)


@router.post("/chat/sessions/{session_id}/messages")
async def send_message(session_id: str, body: ChatRequest, request: Request):
    """Ask a question about the selected sources. Answers stream back as server-sent events."""
    if chat.get_session(session_id) is None:
        raise HTTPException(404, "No such chat.")
    ready = {s["slug"] for s in sources.list_sources() if s["status"] == "ready"}
    slugs = [s for s in body.source_slugs if s in ready]
    if not slugs:
        raise HTTPException(422, "Select at least one processed source to ask about.")

    chat.touch_session(session_id, first_message=body.message)
    engine = _engine(request)

    async def events():
        async for event in engine.stream(session_id, body.message, slugs):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# --- generating episodes ----------------------------------------------------------------------

class GenerateRequest(BaseModel):
    source_slug: str


class DecisionRequest(BaseModel):
    approved: bool
    feedback: str = ""


@router.post("/generate", status_code=202)
async def generate(body: GenerateRequest):
    job = generation.start_generation(body.source_slug)
    spawn(in_thread(generation.advance, job["id"]))
    return generation.describe(job)


@router.get("/jobs")
def list_jobs():
    return [generation.describe(j) for j in generation.list_jobs()]


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = generation.get_job(job_id)
    if job is None:
        raise HTTPException(404, "No such job.")
    return generation.describe(job)


@router.post("/jobs/{job_id}/decision", status_code=202)
async def decide(job_id: str, body: DecisionRequest):
    job = generation.submit_decision(job_id, body.approved, body.feedback)
    spawn(in_thread(generation.advance, job_id, {"approved": body.approved, "feedback": body.feedback}))
    return generation.describe(job)


@router.get("/jobs/{job_id}/audio")
def job_audio(job_id: str):
    """The audio the job is waiting for approval on."""
    gate = (generation.get_job(job_id) or {}).get("gate") or {}
    path = Path(gate.get("audio_path") or "")
    if not path.is_file():
        raise HTTPException(404, "No audio to review for this job.")
    return FileResponse(path, media_type="audio/mpeg")


# --- episodes & publishing ----------------------------------------------------------------------

def _episode(row: dict) -> dict:
    return {
        "id": row["id"], "slug": row["slug"], "title": row["title"], "created_at": row["created_at"],
        "published_at": row["published_at"], "publish_result": row["publish_result"],
        "audio_url": f"/api/episodes/{row['id']}/audio",
    }


@router.get("/episodes")
def list_episodes():
    return [_episode(e) for e in generation.list_episodes()]


@router.get("/episodes/{episode_id}/audio")
def episode_audio(episode_id: str):
    episode = generation.get_episode(episode_id)
    if episode is None or not Path(episode["audio_path"]).is_file():
        raise HTTPException(404, "No audio for this episode.")
    return FileResponse(episode["audio_path"], media_type="audio/mpeg")


@router.post("/episodes/{episode_id}/publish", status_code=202)
async def publish(episode_id: str):
    job = generation.start_publish(episode_id)
    spawn(generation.run_publish(job["id"]))
    return generation.describe(job)
