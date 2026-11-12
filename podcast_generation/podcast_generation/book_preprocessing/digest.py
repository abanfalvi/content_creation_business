from podcast_generation.settings import BOOK_LIST_PATH, DATA_DIR
import hashlib
import json
import re
from datetime import date
from pathlib import Path

from langchain_openrouter import ChatOpenRouter
from pydantic import BaseModel, Field

from podcast_generation.agents.content_specialists.utils import get_book_path
from podcast_generation.agents.models import DIGEST_MODEL

from .toc import find_body_start

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
    text: str = Field(description="One sentence copied verbatim from the book, at most 30 words, no ellipses")
    line: int = Field(description="The number from the [L...] prefix of the line it comes from")


class UnitDigest(BaseModel):
    """What one stretch of a book contains."""
    summary: str = Field(description="Three to five sentences on what this stretch argues and how it argues it. If it is front or back matter or has no real content (acknowledgments, index, notes, ads), say so in one sentence")
    claims: list[Cited] = Field(default_factory=list, description="At most 6 central claims, findings or statistics, most important first")
    frameworks: list[Framework] = Field(default_factory=list, description="Frameworks, models, rules or terms the author names or defines. Empty if there are none")
    examples: list[Cited] = Field(default_factory=list, description="At most 4 stories, studies or cases that carry the argument: who, what happened, what it showed")
    objections: list[Cited] = Field(default_factory=list, description="Places where the author admits a limitation or raises and answers an objection. Empty if there are none")
    voice_quotes: list[Quote] = Field(default_factory=list, description="At most 2 sentences that show how the author writes")


class BookSynthesis(BaseModel):
    """Book-level view built from the section summaries."""
    thesis: str = Field(description="The book's central claim and why a reader should care, in two to four sentences")
    structure: str = Field(description="How the book is built and how its parts build on one another, in three to six sentences, pointing to line ranges")
    central_frameworks: list[str] = Field(default_factory=list, description="The 5 to 8 most central named frameworks or concepts, deduplicated, as the book names them")
    author_voice: str = Field(description="How the author writes: register, use of stories, data, humour, typical moves, in three to five sentences. Base it on the quotes provided")
    objections: str = Field(description="How the book treats counterarguments and its own limits, in two to four sentences, pointing to line ranges. Say so if it barely does")


MAP_SYSTEM = """You are building a reference digest of a non-fiction book. You are given one stretch of the book. \
Every line of it starts with its line number in the book file, like [L120].

Rules:
- Use only the text you are given. Never add outside knowledge, and never guess.
- Every item needs `line`: the number of the line where the item appears. Use only line numbers that appear in the text.
- Be specific. Keep the names, numbers, sample sizes, results and steps of an example. A vague pointer such as \
"the author discusses X" is useless, so write what the book actually says about X.
- Describe in your own words. Only voice_quotes are copied word for word, exactly as written.
- Include only what is really in this stretch. Empty lists are fine."""

REDUCE_SYSTEM = """You are writing the book-level part of a reference digest of a non-fiction book, from summaries of \
its sections. Use only what the summaries and quotes say; never add outside knowledge. Refer to places in the book by \
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
def _render_unit(a: int, b: int, headings: str, digest: UnitDigest, quotes: list[tuple[str, int]]) -> str:
    out = [f"### Lines {a}-{b}" + (f": {headings}" if headings else ""), "", digest.summary.strip(), ""]
    if digest.frameworks:
        out += ["Frameworks and named ideas:"] + [f"- **{f.name}**: {f.definition.strip()} {_cite(f.line, a, b)}" for f in digest.frameworks] + [""]
    for title, items in (("Key claims", digest.claims), ("Examples and cases", digest.examples), ("Objections and limits", digest.objections)):
        if items:
            out += [f"{title}:"] + [f"- {i.text.strip()} {_cite(i.line, a, b)}" for i in items] + [""]
    if quotes:
        out += ["Voice:"] + [f'- "{text}" [L{line}]' for text, line in quotes] + [""]
    return "\n".join(out)


def _render_digest(title: str, author: str, source_name: str, sha: str, total_lines: int, synthesis: BookSynthesis,
                   quotes: list[tuple[str, int]], sections: list[str], failed: list[tuple[int, int]]) -> str:
    head = [
        "---",
        f"source: {source_name}",
        f"source_sha256: {sha}",
        f"source_lines: {total_lines}",
        f"model: {DIGEST_MODEL}",
        f"generated: {date.today().isoformat()}",
        "---",
        f"# Book digest: {title}" + (f" ({author})" if author else ""),
        "",
        "A machine-generated map of the book, built once from its full text. Line numbers like [L120] are lines of the "
        "book file, the same numbers grep and read_book_content use. Use it to decide what to read and where. Check exact "
        "wording, figures and names against the book before relying on them.",
        "",
        "## Thesis", "", synthesis.thesis.strip(), "",
        "## How the book is built", "", synthesis.structure.strip(), "",
    ]
    if synthesis.central_frameworks:
        head += ["## Central frameworks", ""] + [f"- {name}" for name in synthesis.central_frameworks] + [""]
    head += ["## The author's voice", "", synthesis.author_voice.strip(), ""]
    head += [f'- "{text}" [L{line}]' for text, line in quotes[:6]] + [""]
    head += ["## How the book handles objections", "", synthesis.objections.strip(), "", "## Sections", ""]
    tail = []
    if failed:
        tail = ["## Not digested", "", "These stretches could not be processed, so read them directly if they matter:"] \
            + [f"- Lines {a}-{b}" for a, b in failed] + [""]
    return "\n".join(head) + "\n".join(sections) + "\n" + "\n".join(tail)


# Locating the book --------------------------------------------------------------
def _is_current(digest_path: Path, sha: str) -> bool:
    try:
        head = digest_path.read_text(encoding="utf-8")[:600]
    except OSError:
        return False
    match = re.search(r"source_sha256:\s*(\w+)", head)
    return bool(match and match.group(1) == sha)


def find_book(book_title: str) -> tuple[Path, str]:
    """Book file under data/<slug>/ and the author from podcast_generation/book_list.json (empty if unknown)."""
    slug = get_book_path(book_title)
    files = sorted((DATA_DIR / slug).glob("*book_content.md"))
    if not files:
        raise FileNotFoundError(f"No *book_content.md found in data/{slug}/. Preprocess the book first.")
    author = ""
    try:
        data = json.loads(Path(BOOK_LIST_PATH).read_text(encoding="utf-8"))["list_of_books"]
        for genres in data.values():
            for books in genres.values():
                for book in books:
                    if get_book_path(book["title"]) == slug:
                        author = book.get("author", "")
    except (OSError, KeyError, ValueError):
        pass
    return files[0], author


# Generation -------------------------------------------------------------------
async def generate_book_digest(md_path: str | Path, book_title: str, author: str = "", force: bool = False) -> str:
    """Build data/<slug>/book_digest.md for a parsed book. Returns a short status message."""
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
         ("user", f"Book: {book_title}" + (f" by {author}" if author else "") +
                  f"\nThis is lines {a}-{b} of {total} of the book file.\n\n<text>\n{_numbered(lines, a, b)}\n</text>")]
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

    sections, quotes_all, summaries, failed = [], [], [], []
    for (a, b), result in zip(units, results):
        if not isinstance(result, UnitDigest):
            failed.append((a, b))
            continue
        quotes = []
        for q in result.voice_quotes:
            line = _verified_quote_line(q, lines, a, b)
            if line is not None:  # a quote that is not in the book is dropped
                quotes.append((q.text.strip(), line))
        headings = _headings(lines, a, b)
        sections.append(_render_unit(a, b, headings, result, quotes))
        quotes_all += quotes
        names = ", ".join(f.name for f in result.frameworks)
        summaries.append(f"Lines {a}-{b}" + (f" ({headings})" if headings else "") + f": {result.summary.strip()}" + (f" Frameworks: {names}." if names else ""))
    if not sections:
        raise RuntimeError(f"No section of '{book_title}' could be digested, nothing written.")

    reducer = ChatOpenRouter(model=DIGEST_MODEL, temperature=0.2, max_tokens=15_000).with_structured_output(BookSynthesis)
    quote_text = "\n".join(f'- "{t}" [L{n}]' for t, n in quotes_all[:20]) or "(none verified)"
    synthesis = await reducer.ainvoke([
        ("system", REDUCE_SYSTEM),
        ("user", f"Book: {book_title}" + (f" by {author}" if author else "") +
                 "\n\nSection summaries:\n\n" + "\n\n".join(summaries) + f"\n\nVerbatim quotes from the book:\n{quote_text}"),
    ])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_digest(book_title, author, md_path.name, sha, total, synthesis, quotes_all, sections, failed), encoding="utf-8")
    note = f" ({len(failed)} section(s) could not be digested)" if failed else ""
    return f"Digest for '{book_title}' written to {out_path}{note}"


async def digest_book(book_title: str, force: bool = False) -> str:
    """Digest a book that is already parsed under data/<slug>/."""
    md_path, author = find_book(book_title)
    return await generate_book_digest(md_path, book_title, author, force=force)
