import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, StringConstraints

from podcast_generation.services import chat, generation, notebooks, sources

router = APIRouter(prefix="/api")

# A user-chosen name for a notebook or a chat: surrounding spaces are dropped, and it cannot end up empty.
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]

# Background work started by a request. Tasks are only weakly referenced by the loop, so hold them here.
_tasks: set[asyncio.Task] = set()

# To protect the ongoing task against garbage collection
def spawn(coro: Awaitable) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def in_thread(fn: Callable, *args) -> Awaitable:
    return asyncio.to_thread(fn, *args)


@router.get("/health")
def health():
    return {"status": "ok"}


# --- notebooks -------------------------------------------------------------------------------

class NotebookCreate(BaseModel):
    title: Title | None = None


class TitleRequest(BaseModel):
    title: Title


@router.get("/notebooks")
def list_notebooks():
    return notebooks.list_notebooks()


@router.post("/notebooks", status_code=201)
def create_notebook(body: NotebookCreate | None = None):
    return notebooks.create_notebook(body.title if body else None)


@router.get("/notebooks/{notebook_id}")
def get_notebook(notebook_id: str):
    return notebooks.require_notebook(notebook_id)


@router.patch("/notebooks/{notebook_id}")
def rename_notebook(notebook_id: str, body: TitleRequest):
    return notebooks.rename_notebook(notebook_id, body.title)


@router.delete("/notebooks/{notebook_id}", status_code=204)
async def delete_notebook(notebook_id: str, request: Request):
    """Delete a notebook with its sources, chats and episodes. Refused while something in it is still running."""
    notebooks.ensure_deletable(notebook_id)  # before removing anything: 404 if unknown, 409 if busy
    engine = _engine(request)
    for session in chat.list_sessions(notebook_id):
        await engine.delete_thread(session["id"])  # the conversation history, kept in the checkpoint database
    await in_thread(notebooks.delete_notebook, notebook_id)


# --- sources ---------------------------------------------------------------------------------

@router.get("/notebooks/{notebook_id}/sources")
def list_sources(notebook_id: str):
    notebooks.require_notebook(notebook_id)
    return sources.list_sources(notebook_id)


@router.post("/notebooks/{notebook_id}/sources")
async def upload_sources(notebook_id: str, files: list[UploadFile]):
    """Add one or more PDFs to a notebook. Each is validated now and preprocessed in the background."""
    notebooks.require_notebook(notebook_id)
    if not files:
        raise HTTPException(400, "No files were uploaded.")
    results = []
    for upload in files:
        name = upload.filename or "upload.pdf"
        try:
            source = sources.create_source(notebook_id, name, await upload.read())
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


@router.get("/notebooks/{notebook_id}/chat/sessions")
def list_sessions(notebook_id: str):
    notebooks.require_notebook(notebook_id)
    return chat.list_sessions(notebook_id)


@router.post("/notebooks/{notebook_id}/chat/sessions", status_code=201)
def create_session(notebook_id: str):
    notebooks.require_notebook(notebook_id)
    return chat.create_session(notebook_id)


@router.patch("/chat/sessions/{session_id}")
def rename_session(session_id: str, body: TitleRequest):
    session = chat.rename_session(session_id, body.title)
    if session is None:
        raise HTTPException(404, "No such chat.")
    return session


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
    session = chat.get_session(session_id)
    if session is None:
        raise HTTPException(404, "No such chat.")
    # A chat can only draw on the sources of its own notebook.
    ready = {s["slug"] for s in sources.list_sources(session["notebook_id"]) if s["status"] == "ready"}
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


@router.get("/notebooks/{notebook_id}/jobs")
def list_jobs(notebook_id: str):
    notebooks.require_notebook(notebook_id)
    return [generation.describe(j) for j in generation.list_jobs(notebook_id)]


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


@router.get("/notebooks/{notebook_id}/episodes")
def list_episodes(notebook_id: str):
    notebooks.require_notebook(notebook_id)
    return [_episode(e) for e in generation.list_episodes(notebook_id)]


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
