"""Preprocess a book and load it into the vector DB.

Pipeline: PDF -> Markdown (pdf_parsing) -> chunks + metadata (chunking, toc, context) -> Chroma (store)
          -> line-cited book digest for the expert builder and planner (digest)

Strategy: specify chunk location in metadata, extract summary from chunk, add citation.
"""
import math
from pathlib import Path
from typing import Callable

from podcast_generation.agents.content_specialists.utils import get_book_path
from podcast_generation.settings import DATA_DIR

from .chunking import chunk_document
from .digest import generate_book_digest
from .pdf_parsing import parse_pdf, save_markdown
from .store import populate_vector_db

PAGES_PER_BATCH = 200  # MinerU parses the PDF in page batches of this size


async def preprocess_book(
    title: str,
    author: str,
    pdf_path: str | Path,
    end_page: int,
    on_stage: Callable[[str], None] = lambda stage: None,
) -> str:
    """Run the whole ingestion for one book. `on_stage` is called with a short label as each step starts.

    Blocking calls (MinerU, embeddings) run inline, so call this from a worker thread.
    """
    slug = get_book_path(title)
    book_dir = DATA_DIR / slug
    book_dir.mkdir(parents=True, exist_ok=True)
    md_path = book_dir / "book_content.md"

    on_stage("Reading the PDF")
    for run in range(math.ceil(end_page / PAGES_PER_BATCH)):
        first = PAGES_PER_BATCH * run + 1
        last = min(PAGES_PER_BATCH * (run + 1), end_page)
        zip_url = parse_pdf(str(pdf_path), slug, f"{first}-{last}")
        if zip_url is None:
            raise RuntimeError(f"PDF parsing failed for pages {first}-{last} (check MINERU_API_KEY and the server log).")
        save_markdown(zip_url=zip_url, output_path=md_path, append=run > 0)

    on_stage("Splitting into passages")
    chunks = await chunk_document(md_path=md_path, book_title=title, author=author)
    on_stage("Indexing passages")
    populate_vector_db(chunks)
    # Regenerated only if the book file changed since the last digest.
    on_stage("Summarising the book")
    digest_status = await generate_book_digest(md_path, title, author)
    return f"{slug} has been preprocessed successfully!\n{digest_status}"
