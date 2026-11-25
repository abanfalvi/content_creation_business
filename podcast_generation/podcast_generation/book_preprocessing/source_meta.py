import json
from pathlib import Path

from podcast_generation.settings import DATA_DIR

BOOK_FILENAME = "book_content.md"
META_FILENAME = "source.json"
FULL_TEXT_MAX_WORDS = 75_000  # at most this many words: no chunking, the model reads the whole file


def book_file(slug: str) -> Path:
    return DATA_DIR / slug / BOOK_FILENAME


def meta_file(slug: str) -> Path:
    return DATA_DIR / slug / META_FILENAME


def read_meta(slug: str) -> dict:
    try:
        return json.loads(meta_file(slug).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_meta(slug: str, **fields) -> dict:
    """Replace the source's facts (not merge: the previous source with this slug must leave nothing behind)."""
    path = meta_file(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields, indent=2), encoding="utf-8")
    return fields


def update_meta(slug: str, **fields) -> dict:
    """Add facts to the source's existing ones (unlike write_meta, which starts over)."""
    return write_meta(slug, **{**read_meta(slug), **fields})


def delete_meta(slug: str) -> None:
    meta_file(slug).unlink(missing_ok=True)


def is_indexed(slug: str) -> bool:
    """Whether the source has chunks in the vector store (and so a digest and search)."""
    return bool(read_meta(slug).get("indexed", True))


def index_is_stale(slug: str) -> bool:
    """Whether the source's chunks were not built by the current embedding model and chunker.

    Only an indexed source can be stale, and it needs its text file to be rebuilt. A source indexed before
    versions were recorded has no `index_version`, so it counts as stale.
    """
    from .index_version import INDEX_VERSION

    return is_indexed(slug) and book_file(slug).is_file() and read_meta(slug).get("index_version") != INDEX_VERSION


def count_words(text: str) -> int:
    return len(text.split())


NOT_INDEXED_NOTE = (
    "This source is short, so it has no search index: it is read whole instead. "
    "Read data/{slug}/book_content.md with read_book_content, or search that file with grep_search."
)
