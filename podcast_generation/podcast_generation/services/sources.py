import asyncio
import io
import logging
import re
import threading

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from podcast_generation.agents.content_specialists.utils import get_book_path
from podcast_generation.book_preprocessing.pipeline import preprocess_book
from podcast_generation.settings import UPLOAD_DIR

from . import db, notebooks

log = logging.getLogger(__name__)

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
    """Validate and store an uploaded PDF in a notebook and register it as `processing`. Call `ingest` to process it.

    A book's slug names its vector-store entries and working folder, so one book can only live in one notebook.
    """
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

    existing = get_source(slug)
    if existing and existing["status"] != "failed":
        if existing["notebook_id"] == notebook_id:
            raise SourceError(f"{title!r} is already in your sources.", status_code=409)
        other = notebooks.get_notebook(existing["notebook_id"])
        where = f"the notebook {other['title']!r}" if other else "another notebook"
        raise SourceError(f"{title!r} is already in {where}. A book can only be used in one notebook.", status_code=409)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = UPLOAD_DIR / f"{slug}.pdf"
    pdf_path.write_bytes(data)

    row = {
        "slug": slug, "notebook_id": notebook_id, "title": title, "filename": filename, "pdf_path": str(pdf_path),
        "pages": pages, "status": "processing", "stage": "Queued", "error": "", "created_at": db.now(),
    }
    if existing:  # a failed source is replaced by the new upload
        db.update("sources", "slug", slug, **{k: v for k, v in row.items() if k != "slug"})
    else:
        db.insert("sources", row)
    notebooks.touch(notebook_id)
    return get_source(slug)


def ingest(slug: str) -> None:
    """Parse, chunk, embed and digest a registered source. Blocking: run it in a worker thread."""
    with _ingest_lock:
        src = get_source(slug)
        if src is None:
            return
        db.update("sources", "slug", slug, status="processing", stage="Starting", error="")
        try:
            asyncio.run(preprocess_book(
                src["title"], "", src["pdf_path"], src["pages"],
                on_stage=lambda stage: db.update("sources", "slug", slug, stage=stage),
            ))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as the source's error
            log.exception("Ingesting %s failed", slug)
            db.update("sources", "slug", slug, status="failed", stage="", error=str(exc) or type(exc).__name__)
        else:
            db.update("sources", "slug", slug, status="ready", stage="", error="")


def delete_source(slug: str) -> None:
    src = get_source(slug)
    if src is None:
        raise SourceError("No such source.", status_code=404)
    if src["status"] == "processing":
        raise SourceError("This source is still being processed.", status_code=409)
    from podcast_generation.book_preprocessing.store import vector_store

    vector_store.delete(where={"book_slug": slug})
    try:
        (UPLOAD_DIR / f"{slug}.pdf").unlink(missing_ok=True)
    except OSError:
        log.warning("Could not remove the uploaded PDF for %s", slug)
    db.execute("DELETE FROM sources WHERE slug = ?", [slug])


def recover_interrupted() -> None:
    """Sources left `processing` by a previous process can never finish; mark them failed."""
    db.execute(
        "UPDATE sources SET status = 'failed', stage = '', error = ? WHERE status = 'processing'",
        ["Interrupted by a server restart. Upload the file again."],
    )
