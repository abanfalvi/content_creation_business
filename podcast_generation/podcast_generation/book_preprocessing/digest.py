from podcast_generation.settings import DATA_DIR
import hashlib
import json
import logging
import re
from datetime import date
from pathlib import Path

from langchain_openrouter import ChatOpenRouter
from pydantic import BaseModel, Field

from podcast_generation.agents.content_specialists.utils import get_book_path
from podcast_generation.agents.models import DIGEST_MODEL

from .combined import members_of
from .toc import find_body_start

log = logging.getLogger(__name__)

DIGEST_FILENAME = "book_digest.md"
MIN_UNIT_CHARS = 15_000   # close a unit at the next header once it has this much text
MAX_UNIT_CHARS = 40_000   # hard limit on a unit's size
MAX_CONCURRENCY = 5       # parallel map calls, kept low to stay under rate limits


# Structured output ------------------------------------------------------------
class Cited(BaseModel):
    text: str = Field(description="One or two self-contained sentences in your own words, with the specific names, numbers and findings involved")
    line: int = Field(description="The number from the [L...] prefix of the line where this appears")


class Framework(BaseModel):
    name: str = Field(description="The name the author gives the framework, model, rule or term, as written")
    definition: str = Field(description="What it is and how it works, in one or two sentences")
    line: int = Field(description="The number from the [L...] prefix of the line where it is introduced or defined")


class Quote(BaseModel):
    text: str = Field(description="One sentence copied verbatim from the source, at most 30 words, no ellipses")
    line: int = Field(description="The number from the [L...] prefix of the line it comes from")


class UnitDigest(BaseModel):
    """What one stretch of a source contains."""
    summary: str = Field(description="Three to five sentences on what this stretch argues and how it argues it. If it is front or back matter or has no real content (acknowledgments, index, notes, ads), say so in one sentence")
    claims: list[Cited] = Field(default_factory=list, description="At most 6 central claims, findings or statistics, most important first")
    frameworks: list[Framework] = Field(default_factory=list, description="Frameworks, models, rules or terms the author names or defines. Empty if there are none")
    examples: list[Cited] = Field(default_factory=list, description="At most 4 stories, studies or cases that carry the argument: who, what happened, what it showed")
    objections: list[Cited] = Field(default_factory=list, description="Places where the author admits a limitation or raises and answers an objection. Empty if there are none")
    voice_quotes: list[Quote] = Field(default_factory=list, description="At most 2 sentences that show how the author writes")


class BookSynthesis(BaseModel):
    """Source-level view built from the section summaries."""
    thesis: str = Field(description="The source's central claim and why a reader should care, in two to four sentences")
    structure: str = Field(description="How the source is built and how its parts build on one another, in three to six sentences, pointing to line ranges")
    central_frameworks: list[str] = Field(default_factory=list, description="The 5 to 8 most central named frameworks or concepts, deduplicated, as the source names them")
    author_voice: str = Field(description="How the author writes: register, use of stories, data, humour, typical moves, in three to five sentences. Base it on the quotes provided")
    objections: str = Field(description="How the source treats counterarguments and its own limits, in two to four sentences, pointing to line ranges. Say so if it barely does")


MAP_SYSTEM = """You are building a reference digest of a source. You are given one stretch of the source. \
Every line of it starts with its line number in the source file, like [L120].

Rules:
- Use only the text you are given. Never add outside knowledge, and never guess.
- Every item needs `line`: the number of the line where the item appears. Use only line numbers that appear in the text.
- Be specific. Keep the names, numbers, sample sizes, results and steps of an example. A vague pointer such as \
"the author discusses X" is useless, so write what the source actually says about X.
- Describe in your own words. Only voice_quotes are copied word for word, exactly as written.
- Include only what is really in this stretch. Empty lists are fine."""

REDUCE_SYSTEM = """You are writing the source-level part of a reference digest of a source, from summaries of \
its sections. Use only what the summaries and quotes say; never add outside knowledge. Refer to places in the source by \
their line ranges, like L120-410."""


# Splitting --------------------------------------------------------------------
def split_into_units(lines: list[str], first_line: int = 1) -> list[tuple[int, int]]:
    """Cut lines first_line.. into inclusive 1-indexed (start, end) ranges, preferring header lines as cut points."""
    units: list[tuple[int, int]] = []
    start, size = first_line, 0
    for n in range(first_line, len(lines) + 1):
        line = lines[n - 1]
        is_header = line.lstrip().startswith("#")
        if n > start and ((is_header and size >= MIN_UNIT_CHARS) or size + len(line) > MAX_UNIT_CHARS):
            units.append((start, n - 1))
            start, size = n, 0
        size += len(line)
    if start <= len(lines):
        # a short tail is merged into the previous unit instead of costing a call of its own
        if units and size < MIN_UNIT_CHARS // 3:
            units[-1] = (units[-1][0], len(lines))
        else:
            units.append((start, len(lines)))
    return units


def _numbered(lines: list[str], a: int, b: int) -> str:
    return "\n".join(f"[L{n}] {lines[n - 1].rstrip()}" for n in range(a, b + 1) if lines[n - 1].strip())


def _headings(lines: list[str], a: int, b: int, limit: int = 4) -> str:
    found = [re.sub(r"^#+\s*", "", lines[n - 1]).strip() for n in range(a, b + 1) if lines[n - 1].lstrip().startswith("#")]
    shown = " / ".join(found[:limit])
    return shown + (" / ..." if len(found) > limit else "")


# Checks -----------------------------------------------------------------------
def _norm(text: str) -> str:
    text = text.replace("\\", "").translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"}))
    return re.sub(r"\s+", " ", text).strip().lower()


def _verified_quote_line(quote: Quote, lines: list[str], a: int, b: int) -> int | None:
    """Line where the quote really appears in a..b (the claimed one if it matches), else None."""
    target = _norm(quote.text).strip(" \"'")
    if len(target) < 15:
        return None
    if a <= quote.line <= b and target in _norm(lines[quote.line - 1]):
        return quote.line
    return next((n for n in range(a, b + 1) if target in _norm(lines[n - 1])), None)


def _cite(line: int, a: int, b: int) -> str:
    # A line number outside the unit is wrong; say "somewhere in this section" instead of misdirecting.
    return f"[L{line}]" if a <= line <= b else f"[in L{a}-{b}]"


# Rendering --------------------------------------------------------------------
# A digest is kept as data (book_digest.json) and rendered to markdown (book_digest.md). The line numbers in the data
# are those of the source's own file. Rendering with an offset re-bases them onto a file that holds the source at another
# position, which is how one digest serves the source on its own and inside any combined source.
DIGEST_DATA_FILENAME = "book_digest.json"
_LINE_REF = re.compile(r"(?<![A-Za-z0-9])L(\d+)(?:-(\d+))?\b")


def _shift_prose(text: str, offset: int) -> str:
    """Line references the model wrote in prose (L120 or L120-410), moved by `offset`."""
    if not offset:
        return text

    def move(m: re.Match) -> str:
        first = f"L{int(m.group(1)) + offset}"
        return first + (f"-{int(m.group(2)) + offset}" if m.group(2) else "")

    return _LINE_REF.sub(move, text)


def _render_unit(unit: dict, offset: int = 0) -> str:
    a, b = unit["a"] + offset, unit["b"] + offset
    digest = UnitDigest(**unit["digest"])
    headings = unit["headings"]

    def sh(text: str) -> str:
        return _shift_prose(text.strip(), offset)

    out = [f"### Lines {a}-{b}" + (f": {headings}" if headings else ""), "", sh(digest.summary), ""]
    if digest.frameworks:
        out += ["Frameworks and named ideas:"] + [f"- **{f.name}**: {sh(f.definition)} {_cite(f.line + offset, a, b)}" for f in digest.frameworks] + [""]
    for title, items in (("Key claims", digest.claims), ("Examples and cases", digest.examples), ("Objections and limits", digest.objections)):
        if items:
            out += [f"{title}:"] + [f"- {sh(i.text)} {_cite(i.line + offset, a, b)}" for i in items] + [""]
    if unit["quotes"]:
        out += ["Voice:"] + [f'- "{text}" [L{line + offset}]' for text, line in unit["quotes"]] + [""]
    return "\n".join(out)


def _render_sections(data: dict, offset: int = 0) -> str:
    """One source's thesis through its sections (and what could not be digested), line numbers moved by `offset`."""
    synthesis = BookSynthesis(**data["synthesis"])

    def sh(text: str) -> str:
        return _shift_prose(text.strip(), offset)

    head = ["## Thesis", "", sh(synthesis.thesis), "", "## How the source is built", "", sh(synthesis.structure), ""]
    if synthesis.central_frameworks:
        head += ["## Central frameworks", ""] + [f"- {name}" for name in synthesis.central_frameworks] + [""]
    head += ["## The author's voice", "", sh(synthesis.author_voice), ""]
    head += [f'- "{text}" [L{line + offset}]' for text, line in data["quotes"][:6]] + [""]
    head += ["## How the source handles objections", "", sh(synthesis.objections), "", "## Sections", ""]
    sections = [_render_unit(u, offset) for u in data["units"]]
    tail = []
    if data["failed"]:
        tail = ["## Not digested", "", "These stretches could not be processed, so read them directly if they matter:"] \
            + [f"- Lines {a + offset}-{b + offset}" for a, b in data["failed"]] + [""]
    return "\n".join(head) + "\n".join(sections) + "\n" + "\n".join(tail)


def _render_digest(data: dict) -> str:
    author = data["author"]
    front = [
        "---",
        f"source: {data['source_name']}",
        f"source_sha256: {data['sha']}",
        f"source_lines: {data['total_lines']}",
        f"model: {DIGEST_MODEL}",
        f"generated: {date.today().isoformat()}",
        "---",
        f"# Source digest: {data['title']}" + (f" ({author})" if author else ""),
        "",
        "A machine-generated map of the source, built once from its full text. Line numbers like [L120] are lines of the "
        "source file, the same numbers grep and read_book_content use. Use it to decide what to read and where. Check exact "
        "wording, figures and names against the source before relying on them.",
        "",
    ]
    return "\n".join(front) + "\n" + _render_sections(data)


# Locating the source --------------------------------------------------------------
def _is_current(digest_path: Path, sha: str) -> bool:
    try:
        head = digest_path.read_text(encoding="utf-8")[:600]
    except OSError:
        return False
    match = re.search(r"source_sha256:\s*(\w+)", head)
    return bool(match and match.group(1) == sha)


def find_book(book_title: str) -> Path:
    """Source file under data/<slug>/."""
    slug = get_book_path(book_title)
    files = sorted((DATA_DIR / slug).glob("*book_content.md"))
    if not files:
        raise FileNotFoundError(f"No *book_content.md found in data/{slug}/. Preprocess the source first.")
    return files[0]


# Generation -------------------------------------------------------------------
async def generate_book_digest(md_path: str | Path, book_title: str, author: str = "", force: bool = False) -> str:
    """Build data/<slug>/book_digest.md (and the data it is rendered from) for a parsed source. Returns a short status message."""
    md_path = Path(md_path)
    sha = hashlib.sha256(md_path.read_bytes()).hexdigest()
    out_path = DATA_DIR / get_book_path(book_title) / DIGEST_FILENAME
    if not force and _is_current(out_path, sha):
        return f"Digest for '{book_title}' is up to date: {out_path}"

    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    content = "".join(lines)
    first_line = content.count("\n", 0, find_body_start(content)) + 1  # skip front matter and the TOC
    units = split_into_units(lines, first_line)

    mapper = ChatOpenRouter(model=DIGEST_MODEL, temperature=0.2, max_tokens=15_000).with_structured_output(UnitDigest)
    total = len(lines)
    prompts = [
        [("system", MAP_SYSTEM),
         ("user", f"Source: {book_title}" + (f" by {author}" if author else "") +
                  f"\nThis is lines {a}-{b} of {total} of the source file.\n\n<text>\n{_numbered(lines, a, b)}\n</text>")]
        for a, b in units
    ]
    print(f"Digesting '{book_title}': {len(units)} sections from line {first_line} to {total}")
    results = await mapper.abatch(prompts, config={"max_concurrency": MAX_CONCURRENCY}, return_exceptions=True)
    for i, result in enumerate(results):  # one more try for the units that failed
        if not isinstance(result, UnitDigest):
            try:
                results[i] = await mapper.ainvoke(prompts[i])
            except Exception as err:
                print(f"Section lines {units[i][0]}-{units[i][1]} failed: {err!r}")

    unit_data, quotes_all, summaries, failed = [], [], [], []
    for (a, b), result in zip(units, results):
        if not isinstance(result, UnitDigest):
            failed.append([a, b])
            continue
        quotes = []
        for q in result.voice_quotes:
            line = _verified_quote_line(q, lines, a, b)
            if line is not None:  # a quote that is not in the source is dropped
                quotes.append([q.text.strip(), line])
        headings = _headings(lines, a, b)
        unit_data.append({"a": a, "b": b, "headings": headings, "digest": result.model_dump(), "quotes": quotes})
        quotes_all += quotes
        names = ", ".join(f.name for f in result.frameworks)
        summaries.append(f"Lines {a}-{b}" + (f" ({headings})" if headings else "") + f": {result.summary.strip()}" + (f" Frameworks: {names}." if names else ""))
    if not unit_data:
        raise RuntimeError(f"No section of '{book_title}' could be digested, nothing written.")

    reducer = ChatOpenRouter(model=DIGEST_MODEL, temperature=0.2, max_tokens=15_000).with_structured_output(BookSynthesis)
    quote_text = "\n".join(f'- "{t}" [L{n}]' for t, n in quotes_all[:20]) or "(none verified)"
    synthesis = await reducer.ainvoke([
        ("system", REDUCE_SYSTEM),
        ("user", f"Source: {book_title}" + (f" by {author}" if author else "") +
                 "\n\nSection summaries:\n\n" + "\n\n".join(summaries) + f"\n\nVerbatim quotes from the source:\n{quote_text}"),
    ])

    data = {
        "title": book_title, "author": author, "source_name": md_path.name, "sha": sha, "total_lines": total,
        "synthesis": synthesis.model_dump(), "units": unit_data, "quotes": quotes_all, "failed": failed,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    (out_path.parent / DIGEST_DATA_FILENAME).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")  # first: the .md marks it current
    out_path.write_text(_render_digest(data), encoding="utf-8")
    note = f" ({len(failed)} section(s) could not be digested)" if failed else ""
    return f"Digest for '{book_title}' written to {out_path}{note}"


def _load_digest_data(slug: str, sha: str) -> dict | None:
    """The data a source's digest was built from, if it is the digest of the source as it is now."""
    try:
        data = json.loads((DATA_DIR / slug / DIGEST_DATA_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if data.get("sha") == sha else None


async def source_digest_data(book_title: str, author: str = "", force: bool = False) -> tuple[dict, bool]:
    """(the digest data of one source, whether it had to be built now). A source is digested once, however it is used."""
    md_path = find_book(book_title)
    slug = get_book_path(book_title)
    sha = hashlib.sha256(md_path.read_bytes()).hexdigest()
    data = None if force else _load_digest_data(slug, sha)
    if data is not None:
        return data, False
    # force: a digest written before the data was kept has a current .md but no data to re-base, so it is built again once
    log.info(await generate_book_digest(md_path, book_title, author, force=True))
    data = _load_digest_data(slug, sha)
    if data is None:
        raise RuntimeError(f"The digest of '{book_title}' was written but could not be read back.")
    return data, True


async def digest_combined(book_title: str, force: bool = False) -> str:
    """Assemble the digest of a combined source from the digests of its sources, one block each.

    Each source is digested on its own (once, however many episodes use it, in whatever combination), so a section
    never spans two sources and each has its own thesis and voice. Putting the blocks together costs no model calls:
    their line numbers are moved to where the source sits in the combined file.
    """
    slug = get_book_path(book_title)
    md_path = find_book(book_title)
    members = members_of(slug)
    n, blocks, built = len(members), [], 0
    for i, m in enumerate(members, start=1):
        name = m["title"] + (f" ({m['author']})" if m["author"] else "")
        head = f"# Source {i} of {n}: {name} (lines {m['start']}-{m['end']})"
        if not m["indexed"]:
            blocks.append(f"{head}\n\nA short transcript: there is no digest of it. Read it whole, at lines {m['start']}-{m['end']} of this file.\n")
            continue
        if "shift" not in m:
            raise RuntimeError(f"'{book_title}' was combined before its sources' positions were recorded. Start the episode again.")
        data, was_built = await source_digest_data(m["title"], m["author"], force)
        built += was_built
        blocks.append(f"{head}\n\n" + _render_sections(data, m["shift"]))

    front = [
        "---",
        f"source: {md_path.name}",
        f"source_sha256: {hashlib.sha256(md_path.read_bytes()).hexdigest()}",
        f"source_lines: {len(md_path.read_text(encoding='utf-8').splitlines())}",
        f"sources: {n}",
        f"model: {DIGEST_MODEL}",
        f"generated: {date.today().isoformat()}",
        "---",
        f"# Source digest: {book_title}",
        "",
        f"A machine-generated map of {n} independent sources joined into one file, with one block per source: each has its own "
        "thesis, frameworks, voice and objections. Line numbers like [L120] are lines of the combined source file, the same "
        "numbers grep and read_book_content use. Use it to decide what to read and where. Check exact wording, figures and "
        "names against the source before relying on them, and never attribute one source's claims to another.",
        "",
    ]
    out_path = DATA_DIR / slug / DIGEST_FILENAME
    out_path.write_text("\n".join(front) + "\n" + "\n".join(blocks), encoding="utf-8")
    return f"Digest for '{book_title}' assembled from {n} sources ({built} digested now): {out_path}"


async def digest_book(book_title: str, force: bool = False) -> str:
    """Digest a source that is already parsed under data/<slug>/. A combined source is assembled from its sources' digests."""
    if members_of(get_book_path(book_title)):
        return await digest_combined(book_title, force)
    md_path = find_book(book_title)
    return await generate_book_digest(md_path, book_title, force=force)
