"""A combined source: several ingested sources joined into one virtual source, so one episode can draw on all of them.

Every agent, tool and file in the content and production stages is keyed on a source's slug (`data/<slug>/...`), so
the combined source is simply one more slug with its own folder:

- `data/<slug>/book_content.md` holds every member's text one after the other, each under a banner line
  (`=== SOURCE 2 of 3: Title ===`) and behind an index of which lines belong to which source. Line numbers, grep,
  line-range reads, the digest and the plan's citations therefore work exactly as they do for a single source.
- `data/<slug>/source.json` lists the members, which is how retrieval knows to search all of their chunks, and where
  each sits in the text, which is how their own digests are moved into the combined digest.

The slug is derived from the title the same way as for any source (`get_book_path`), so the title is what the agents
are given, and a different set of sources gets a different folder.
"""
from __future__ import annotations

import glob
from pathlib import Path

from podcast_generation.agents.content_specialists.utils import get_book_path
from podcast_generation.settings import DATA_DIR

from .source_meta import BOOK_FILENAME, book_file, read_meta, write_meta

COMBINED_KIND = "combined"
MAX_TITLE_CHARS = 90
BANNER = "=== SOURCE {i} of {n}: {title} ==="
END_BANNER = "=== END OF SOURCE {i} of {n} ==="


def combined_title(titles: list[str]) -> str:
    """The title the combined source goes by: the member titles joined, or the first plus a count if that gets long."""
    joined = " + ".join(titles)
    if len(joined) <= MAX_TITLE_CHARS:
        return joined
    return f"{titles[0]} + {len(titles) - 1} more sources"


def members_of(slug: str) -> list[dict]:
    """The sources a combined source is made of ([{slug, title, author, indexed}]); empty for an ordinary source."""
    meta = read_meta(slug)
    return list(meta.get("members") or []) if meta.get("kind") == COMBINED_KIND else []


def _member_file(slug: str) -> Path:
    files = sorted(glob.glob(str(DATA_DIR / slug / f"*{BOOK_FILENAME}")))
    if not files:
        raise FileNotFoundError(f"No *{BOOK_FILENAME} found in data/{slug}/. Preprocess the source first.")
    return Path(files[0])


def prepare_combined_source(sources: list[dict]) -> tuple[str, str]:
    """Write (or refresh) the combined source for these ingested sources and return its (slug, title).

    `sources` are rows of the sources table, in the order they should appear. The text file is only rewritten when
    it changed, so an unchanged set keeps its digest.
    """
    if len(sources) < 2:
        raise ValueError("A combined source needs at least two sources.")
    members = [
        {"slug": s["slug"], "title": s["title"], "author": s.get("author") or "", "indexed": bool(s.get("indexed", 1))}
        for s in sources
    ]
    title = combined_title([m["title"] for m in members])
    slug = get_book_path(title)
    n = len(members)

    raws = [_member_file(m["slug"]).read_text(encoding="utf-8") for m in members]
    bodies = [raw.strip("\n") for raw in raws]
    leading = [len(raw) - len(raw.lstrip("\n")) for raw in raws]  # blank lines dropped from the top of each source

    # The index at the top says which lines are which source, so its length has to be known before the offsets.
    header_lines = 4 + n + 1
    ranges, line = [], header_lines + 1
    for i, body in enumerate(bodies, start=1):
        start = line  # the banner line
        end = start + body.count("\n") + 2  # banner, the body's lines, end banner
        ranges.append((start, end))
        line = end + 2  # a blank line separates sources

    # Where each source sits, so a digest of the source on its own can be moved into this file: line n of the
    # source is line n + shift of this one.
    for m, (a, b), lead in zip(members, ranges, leading):
        m["start"], m["end"], m["shift"] = a, b, a - lead

    index = [
        f"Combined source: {title}",
        f"This file joins {n} independent sources into one text. Each is introduced by a banner line and closed by an end banner.",
        "Each source has its own thesis, author and voice. Do not attribute one source's claims to another.",
        "Sources and the lines they occupy:",
    ]
    for i, (m, (a, b)) in enumerate(zip(members, ranges), start=1):
        by = f" ({m['author']})" if m["author"] else ""
        index.append(f"{i}. {m['title']}{by}: lines {a}-{b}")
    index.append("")

    out: list[str] = index
    for i, (m, body) in enumerate(zip(members, bodies), start=1):
        out += [BANNER.format(i=i, n=n, title=m["title"]), *body.split("\n"), END_BANNER.format(i=i, n=n), ""]
    text = "\n".join(out).rstrip("\n") + "\n"

    target = book_file(slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.read_text(encoding="utf-8") != text:
        target.write_text(text, encoding="utf-8")
    # Searchable if any member is; the members that are not (short transcripts) are only in the text file.
    write_meta(slug, kind=COMBINED_KIND, members=members, indexed=any(m["indexed"] for m in members), title=title)
    return slug, title
