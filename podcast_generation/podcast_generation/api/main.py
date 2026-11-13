import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from podcast_generation.services import chat, db, generation, notebooks, sources
from podcast_generation.settings import FRONTEND_DIST

from .routes import router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    sources.recover_interrupted()
    generation.recover_interrupted()
    app.state.chat = chat.ChatEngine()  # connects to its checkpoint database on first use
    try:
        yield
    finally:
        await app.state.chat.aclose()


app = FastAPI(title="Level Up Lab", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(notebooks.NotebookError)
@app.exception_handler(sources.SourceError)
@app.exception_handler(generation.GenerationError)
async def _domain_error(_: Request, exc: Exception):
    return JSONResponse({"detail": str(exc)}, status_code=getattr(exc, "status_code", 400))


if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="web")


def run() -> None:
    """Entry point for `uv run podcast-server`."""
    import uvicorn

    uvicorn.run(app, host=os.getenv("PODCAST_HOST", "127.0.0.1"), port=int(os.getenv("PODCAST_PORT", "8000")))
