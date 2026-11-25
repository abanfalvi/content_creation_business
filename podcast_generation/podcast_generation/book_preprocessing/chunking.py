"""Split a book's Markdown into chunks and tag them with chapter + context metadata."""
from tqdm import tqdm
from pathlib import Path
from bisect import bisect_right
import json, re
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from podcast_generation.agents.content_specialists.utils import get_book_path
from podcast_generation.book_preprocessing.context import create_chunk_surrounding_summaries
from podcast_generation.book_preprocessing.index_version import CHUNK_SIZE, INDEX_VERSION
from podcast_generation.book_preprocessing.toc import extract_toc_titles, match_toc_to_headers

_PAGE_MARKER_RE = re.compile(r"\{(\d+)\}-{8,}\n\n")
_FRONT_MATTER_RE = re.compile(
    r"^(contents|table of contents|title|copyright|dedication|acknowledgements?|"
    r"about the author|index|foreword|preface|notes|bibliography)$"
)
_OPENER_RE = re.compile(r"^(introduction|prologue|chapter|part|book)\b|^\d+(?:\.\d+)*$", re.I)
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_NUMBER_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    "fifteen|sixteen|seventeen|eighteen|nineteen|twenty|first|second|third|fourth|fifth|"
    "sixth|seventh|eighth|ninth|tenth"
)
_LABEL_RE = re.compile(
    rf"""^(?:
        (?:part|chapter|section|book)\s+(?:\d+|[ivxlcdm]+|{_NUMBER_WORDS})\b
        |\d+(?:\.\d+)*(?=\s*[.):\-–—]|\s)
        |[ivxlcdm]+(?=[.)]\s)
    )[\s.):\-–—]*""",
    re.I | re.X,
)

def _norm(text: str) -> str:
    """Comparable form of a title: no markup, numbering, punctuation or case."""
    t = _LINK_RE.sub(r"\1", text).lower()
    t = re.sub(r"[#*_`>|]", " ", t)
    t = re.sub(r"[\-–—‑/]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    unlabelled = _LABEL_RE.sub("", t, count=1)
    # "Part One" on its own would become empty - keep the label then.
    t = unlabelled if re.search(r"\w", unlabelled) else t
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()

def flatten_toc(nodes, depth=0):
    for node in nodes or []:
        yield (node.get("title") or ""), node.get("page"), depth
        yield from flatten_toc(node.get("children"), depth + 1)

def index_start_from_bookmarks(md: str, bookmarks: list[dict]) -> list[tuple[int, dict[str, Any]]]:
    """(character offset, {"title", "depth"}) for each bookmark that opens a section, in book order."""
    offsets = {int(m.group(1)): m.end() for m in _PAGE_MARKER_RE.finditer(md)}
    # At most one level deep: a section inside a chapter is not a chapter of its own.
    flat = [(title, page, depth) for title, page, depth in flatten_toc(bookmarks) if depth <= 1]
    starts = {}
    for i, (title, page, depth) in enumerate(flat):
        key = _norm(title)
        # A bookmark on a page the markdown has no marker for cannot be placed.
        if not (page in offsets and key and not _FRONT_MATTER_RE.match(key)):
            continue
        # A heading with a deeper one right after it names the group that follows, not a section of its own.
        if i + 1 < len(flat) and flat[i + 1][2] > depth:
            continue
        starts[offsets[page]] = {"title": title, "depth": depth}
    return sorted(starts.items())


async def chunk_document(md_path: str, book_title: str, author: str):
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Title is for display; book_slug is the key retrieval filters on (same slug as data/<slug>/).
    book_doc = Document(
        page_content=content,
        metadata={"Title": book_title, "book_slug": get_book_path(book_title), "Author": author, "index_version": INDEX_VERSION},
    )
    separators = [
        r"\n#{1,6}\s",  # markdown headers
        r"\{\d+\}-{8,}\n\n", # page markers (no capture group: re.split would emit it as an extra item)
        "\n\n\n",       # chapter/section breaks
        "\n\n",         # paragraph breaks
        "\n",           # line breaks
        ". ",           # sentence end
        "! ",
        "? ",
        "; ",
        ", ",
        " ",            # word boundary
        "",             # character fallback
    ]

    recursive_splitter = RecursiveCharacterTextSplitter(separators, is_separator_regex=True, chunk_size=CHUNK_SIZE, add_start_index=True)
    splits = recursive_splitter.split_documents([book_doc])
    print("Total number of splits created: ", len(splits))

    # The PDF's own outline places chapters exactly; the Markdown scan is the fallback for sources without one.
    starts: list[tuple[int, dict[str, Any]]] = []
    toc_path = Path(md_path).with_suffix(".metadata.json")
    if toc_path.is_file():
        try:
            toc_content = json.loads(toc_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            toc_content = {}
        if isinstance(toc_content, dict):
            toc_content = toc_content.get("pdf_bookmarks") or []
        starts = index_start_from_bookmarks(content, toc_content)

    if starts:
        offsets = [offset for offset, _ in starts]
        for chunk in tqdm(splits):
            # Last section that opens at or before this chunk; -1 means it sits in the front matter.
            i = bisect_right(offsets, chunk.metadata['start_index']) - 1
            if i >= 0:
                chunk.metadata['chapter'] = starts[i][1]["title"]
    else:
        boundaries = match_toc_to_headers(content, extract_toc_titles(content))
        for boundary in boundaries:
            for chunk in tqdm(splits):
                if boundary[1] <= chunk.metadata['start_index']:
                    chunk.metadata['chapter'] = boundary[0]

    chunks = await create_chunk_surrounding_summaries(splits)
    return chunks