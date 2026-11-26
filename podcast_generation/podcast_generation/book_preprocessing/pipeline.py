"""Preprocess a book and load it into the vector DB.

Pipeline: PDF -> Markdown (pdf_parsing) -> chunks + metadata (chunking, toc, context) -> Chroma (store)

The line-cited book digest (digest) is not built here: only podcast generation needs it, so it is built there.

Strategy: specify chunk location in metadata, extract summary from chunk, add citation.

A YouTube video takes the same path from its transcript on (`preprocess_video`), except that a short one is not indexed.
"""
import asyncio
import math
import tempfile
from pathlib import Path
from typing import Callable

from podcast_generation.agents.content_specialists.utils import get_book_path
from podcast_generation.settings import DATA_DIR

from .chunking import chunk_document
from .index_version import INDEX_VERSION
from .pdf_parsing import parse_pdf
from .source_meta import FULL_TEXT_MAX_WORDS, book_file, count_words, read_meta, update_meta, write_meta
from .store import delete_book_vectors, populate_vector_db
from .video import download_audio, transcribe_audio, video_id

async def preprocess_book(
    title: str,
    author: str,
    pdf_path: str | Path,
    end_page: int,
    on_stage: Callable[[str], None] = lambda stage: None,
) -> str:
    """Run the whole ingestion for one book. `on_stage` is called with a short label as each step starts.

    Blocking calls (embeddings) run inline, so call this from a worker thread.
    """
    slug = get_book_path(title)
    book_dir = DATA_DIR / slug
    book_dir.mkdir(parents=True, exist_ok=True)
    md_path = book_file(slug)
    # A text left by a video that had this slug is not this book's text.
    if not (md_path.is_file() and read_meta(slug).get("kind", "pdf") == "pdf"):
        on_stage("Reading the PDF")
        # for run in range(math.ceil(end_page / PAGES_PER_BATCH)):
        #     first = PAGES_PER_BATCH * run + 1
        #     last = min(PAGES_PER_BATCH * (run + 1), end_page)
        #     zip_url = parse_pdf(str(pdf_path), slug, f"{first}-{last}")
        #     if zip_url is None:
        #         raise RuntimeError(f"PDF parsing failed for pages {first}-{last} (check MINERU_API_KEY and the server log).")
        #     save_markdown(zip_url=zip_url, output_path=str(md_path), append=run > 0)

        await parse_pdf(str(pdf_path), str(md_path), with_bookmark=True)
    write_meta(slug, kind="pdf", title=title, indexed=True)
    await _index(md_path, title, author, on_stage)
    update_meta(slug, index_version=INDEX_VERSION)  # only once indexing worked: a half-built index stays stale
    return f"{slug} has been preprocessed successfully!"


async def reindex_source(
    slug: str,
    title: str,
    author: str,
    on_stage: Callable[[str], None] = lambda stage: None,
) -> None:
    """Chunk, summarise and embed an already ingested source again, with the current embedding model and chunker.

    The text file stays as it is (no PDF parsing or transcription is paid for again); the source's chunks in
    the current collections are replaced. Use it when `source_meta.index_is_stale(slug)`.
    """
    md_path = book_file(slug)
    if not md_path.is_file():
        raise FileNotFoundError(f"{slug} has no text file to index; add the source again.")
    await _index(md_path, title, author, on_stage)
    _mark_indexed(slug)


def _mark_indexed(slug: str) -> None:
    """Record that the index was built with the current chunker (only once indexing worked: a half-built index stays stale)."""
    update_meta(slug, index_version=INDEX_VERSION, **({"timed_chunks": True} if read_meta(slug).get("kind") == "youtube" else {}))


async def _index(md_path: Path, title: str, author: str, on_stage: Callable[[str], None]) -> None:
    on_stage("Splitting into passages")
    chunks = await chunk_document(md_path=str(md_path), book_title=title, author=author)
    on_stage("Indexing passages")
    populate_vector_db(chunks)


async def preprocess_video(
    title: str,
    url: str,
    channel: str = "",
    duration: float = 0,
    on_stage: Callable[[str], None] = lambda stage: None,
) -> str:
    """Ingest a YouTube video: audio -> transcript (video) -> the same text file a book has.

    A transcript of at most FULL_TEXT_MAX_WORDS words is not chunked or embedded: the agents read the whole file.
    A longer one goes through the same chunking and indexing as a book.
    """
    slug = get_book_path(title)
    md_path = book_file(slug)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    vid = video_id(url)

    # A transcript already made for this very video (an earlier attempt that failed later) is not paid for twice.
    if not (md_path.is_file() and read_meta(slug).get("video_id") == vid):
        with tempfile.TemporaryDirectory() as tmp:
            on_stage("Downloading the audio")
            audio = await asyncio.to_thread(download_audio, url, Path(tmp))
            on_stage("Transcribing the audio")
            transcript = await transcribe_audio(
                audio, Path(tmp), title, channel, url, duration,
                on_progress=lambda done, total: on_stage(f"Transcribing the audio ({done}/{total})"),
            )
        md_path.write_text(transcript, encoding="utf-8")

    words = count_words(md_path.read_text(encoding="utf-8"))
    indexed = words > FULL_TEXT_MAX_WORDS
    write_meta(slug, kind="youtube", title=title, video_id=vid, url=url, channel=channel, words=words, indexed=indexed)
    if indexed:
        await _index(md_path, title, channel, on_stage)
        _mark_indexed(slug)
        return f"{slug}: {words} words transcribed and indexed."
    delete_book_vectors(slug)  # an earlier, longer ingestion of this slug must not stay searchable
    return f"{slug}: {words} words transcribed; short enough to read whole, so it is not indexed."
