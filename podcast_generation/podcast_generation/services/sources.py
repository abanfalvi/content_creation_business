import asyncio
import io
import logging
import re
import threading

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from podcast_generation.agents.content_specialists.utils import get_book_path
from podcast_generation.book_preprocessing import source_meta, video
from podcast_generation.book_preprocessing.pipeline import preprocess_book, preprocess_video, reindex_source
from podcast_generation.settings import UPLOAD_DIR

from . import db, notebooks

log = logging.getLogger(__name__)

MAX_VIDEO_SECONDS = 8 * 3600  # longer videos are refused before anything is downloaded

# MinerU and the embedding API are rate limited, so books are ingested one at a time.
_ingest_lock = threading.Lock()


class SourceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def title_from_filename(filename: str) -> str:
    stem = re.sub(r"\.pdf$", "", filename.strip(), flags=re.I)
    return re.sub(r"\s+", " ", stem.replace("_", " ")).strip()


def list_sources(notebook_id: str) -> list[dict]:
    return db.query("SELECT * FROM sources WHERE notebook_id = ? ORDER BY created_at", [notebook_id])


def get_source(slug: str) -> dict | None:
    return db.one("SELECT * FROM sources WHERE slug = ?", [slug])


def create_source(notebook_id: str, filename: str, data: bytes) -> dict:
    """Validate and store an uploaded PDF in a notebook and register it as `processing`. Call `ingest` to process it."""
    if not filename.lower().endswith(".pdf"):
        raise SourceError(f"{filename}: only PDF files can be added.")
    title = title_from_filename(filename)
    slug = get_book_path(title)
    if not slug:
        raise SourceError(f"{filename}: could not derive a title from the file name.")
    try:
        pages = len(PdfReader(io.BytesIO(data)).pages)
    except (PyPdfError, ValueError, OSError) as exc:
        raise SourceError(f"{filename}: not a readable PDF ({exc}).") from exc
    if pages == 0:
        raise SourceError(f"{filename}: the PDF has no pages.")

    existing = _check_free(notebook_id, slug, title)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = UPLOAD_DIR / f"{slug}.pdf"
    pdf_path.write_bytes(data)

    return _register(notebook_id, slug, existing, {
        "title": title, "filename": filename, "pdf_path": str(pdf_path), "pages": pages,
        "kind": "pdf", "url": "", "author": "", "duration": 0, "indexed": 1,
    })


def create_video_source(notebook_id: str, url: str) -> dict:
    """Validate a YouTube link and register the video as a `processing` source. Call `ingest` to process it.

    Reads the video's title and length from YouTube, so it makes a network call: run it in a worker thread.
    """
    vid = video.video_id(url)
    if vid is None:
        raise SourceError("That is not a link to a single YouTube video.")
    canonical = video.canonical_url(vid)
    try:
        info = video.fetch_video_info(canonical)
    except video.VideoError as exc:
        raise SourceError(f"Could not read that video: {exc}") from exc
    if info["is_live"]:
        raise SourceError("A live stream cannot be added until it has ended.")
    if info["duration"] > MAX_VIDEO_SECONDS:
        raise SourceError(f"That video is {info['duration'] // 3600} hours long; the limit is {MAX_VIDEO_SECONDS // 3600} hours.")
    title = video.clean_title(info["title"])
    slug = get_book_path(title)
    if not slug:
        raise SourceError("Could not derive a title from that video.")

    existing = _check_free(notebook_id, slug, title)
    return _register(notebook_id, slug, existing, {
        "title": title, "filename": canonical, "pdf_path": "", "pages": 0,
        "kind": "youtube", "url": canonical, "author": info["channel"], "duration": info["duration"], "indexed": 1,
    })


def _check_free(notebook_id: str, slug: str, title: str) -> dict | None:
    """The failed source this one replaces, if any. Raises if a working source already has the slug.

    A source's slug names its vector-store entries and working folder, so it can only live in one notebook.
    """
    existing = get_source(slug)
    if existing and existing["status"] != "failed":
        if existing["notebook_id"] == notebook_id:
            raise SourceError(f"{title!r} is already in your sources.", status_code=409)
        other = notebooks.get_notebook(existing["notebook_id"])
        where = f"the notebook {other['title']!r}" if other else "another notebook"
        raise SourceError(f"{title!r} is already in {where}. A book can only be used in one notebook.", status_code=409)
    return existing


def _register(notebook_id: str, slug: str, existing: dict | None, fields: dict) -> dict:
    row = {
        "slug": slug, "notebook_id": notebook_id, **fields,
        "status": "processing", "stage": "Queued", "error": "", "created_at": db.now(),
    }
    if existing:  # a failed source is replaced by the new one
        db.update("sources", "slug", slug, **{k: v for k, v in row.items() if k != "slug"})
    else:
        db.insert("sources", row)
    notebooks.touch(notebook_id)
    return get_source(slug)


def ingest(slug: str) -> None:
    """Parse or transcribe, then chunk and embed a registered source. Blocking: run it in a worker thread."""
    with _ingest_lock:
        src = get_source(slug)
        if src is None:
            return
        db.update("sources", "slug", slug, status="processing", stage="Starting", error="")

        def on_stage(stage: str) -> None:
            db.update("sources", "slug", slug, stage=stage)

        try:
            if src["kind"] == "youtube":
                asyncio.run(preprocess_video(src["title"], src["url"], src["author"], src["duration"], on_stage=on_stage))
            else:
                asyncio.run(preprocess_book(src["title"], src["author"], src["pdf_path"], src["pages"], on_stage=on_stage))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as the source's error
            log.exception("Ingesting %s failed", slug)
            db.update("sources", "slug", slug, status="failed", stage="", error=str(exc) or type(exc).__name__)
        else:
            # A short transcript is read whole, so it has no chunks to search and no digest.
            db.update("sources", "slug", slug, status="ready", stage="", error="", indexed=int(source_meta.is_indexed(slug)))


def stale_sources() -> list[dict]:
    """Ready sources whose search index was built by an older embedding model or chunker.

    Their chunks are not in the current vector collections, so a search finds nothing in them until `reindex`.
    """
    ready = db.query("SELECT * FROM sources WHERE status = 'ready' AND indexed = 1 ORDER BY created_at")
    return [s for s in ready if source_meta.index_is_stale(s["slug"])]


def reindex(slug: str, on_stage=lambda stage: None) -> None:
    """Rebuild a ready source's search index from its stored text. Blocking: run it in a worker thread.

    Chunking, the neighbourhood summaries (one model call per passage) and the embeddings are paid for again;
    the PDF is not parsed again. If it fails the source stays `ready` and stale, so it can be retried; the
    error is raised.
    """
    with _ingest_lock:
        src = get_source(slug)
        if src is None or src["status"] != "ready":
            return
        db.update("sources", "slug", slug, status="processing", stage="Rebuilding the search index", error="")

        def stage(label: str) -> None:
            db.update("sources", "slug", slug, stage=label)
            on_stage(label)

        try:
            asyncio.run(reindex_source(slug, src["title"], src["author"], on_stage=stage))
        except BaseException:
            db.update("sources", "slug", slug, status="ready", stage="")
            raise
        db.update("sources", "slug", slug, status="ready", stage="", error="")


def delete_source(slug: str) -> None:
    src = get_source(slug)
    if src is None:
        raise SourceError("No such source.", status_code=404)
    if src["status"] == "processing":
        raise SourceError("This source is still being processed.", status_code=409)
    from podcast_generation.book_preprocessing.store import delete_book_vectors

    delete_book_vectors(slug)
    source_meta.delete_meta(slug)  # so a later source with this slug does not inherit its `indexed` flag
    try:
        (UPLOAD_DIR / f"{slug}.pdf").unlink(missing_ok=True)
    except OSError:
        log.warning("Could not remove the uploaded PDF for %s", slug)
    db.execute("DELETE FROM sources WHERE slug = ?", [slug])


def recover_interrupted() -> None:
    """Sources left `processing` by a previous process can never finish; mark them failed."""
    db.execute(
        "UPDATE sources SET status = 'failed', stage = '', error = ? WHERE status = 'processing'",
        ["Interrupted by a server restart. Add the source again."],
    )
