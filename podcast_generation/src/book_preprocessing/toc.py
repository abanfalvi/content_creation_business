"""Table-of-contents extraction and matching of TOC entries to Markdown headers.

Written to cope with the messy Markdown that PDF parsers produce, without any
book-specific rules:

* the contents heading may be "Contents" / "Table of Contents", with or without ``#``;
* the TOC may be one plain list, or have some entries turned into ``#`` headers by OCR;
* entries may carry numbering ("3.", "Chapter 3", "Part One"), page numbers or dot leaders;
* the body headers may differ from the TOC in case, numbering, punctuation or subtitle.
"""
import difflib
import re

_CONTENTS_RE = re.compile(r"^(?:#{1,6}[ \t]*)?(?:table[ \t]+of[ \t]+)?contents[ \t]*$", re.I | re.M)
_HEADER_RE = re.compile(r"^#{1,6}[ \t]*(.+?)[ \t]*$")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")

_NUMBER_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    "fifteen|sixteen|seventeen|eighteen|nineteen|twenty|first|second|third|fourth|fifth|"
    "sixth|seventh|eighth|ninth|tenth"
)
# Leading numbering that differs between a TOC line and the matching header:
# "Part One", "Chapter 3:", "3.", "3.2", "IV."
_LABEL_RE = re.compile(
    rf"""^(?:
        (?:part|chapter|section|book)\s+(?:\d+|[ivxlcdm]+|{_NUMBER_WORDS})\b
        |\d+(?:\.\d+)*(?=\s*[.):\-–—]|\s)
        |[ivxlcdm]+(?=[.)]\s)
    )[\s.):\-–—]*""",
    re.I | re.X,
)
# Trailing page number after dot leaders / a tab / a wide gap
_PAGE_NUMBER_RE = re.compile(r"(?:\s*[.·…]{2,}\s*|\t+|\s{3,})(?:\d+|[ivxlcdm]+)\s*$", re.I)


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


def _clean_entry(text: str) -> str:
    text = _LINK_RE.sub(r"\1", text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"^[\s>+•\-]+", "", text)
    text = _PAGE_NUMBER_RE.sub("", text)
    return text.strip()


def _is_prose(line: str) -> bool:
    """A long sentence-like line: TOC entries are short, body paragraphs are not."""
    return len(line.split()) >= 25 and line.rstrip()[-1] in ".!?\"'”’)"


def _scan_toc(content: str) -> tuple[list[str], int]:
    """Return (TOC entries, offset where the TOC ends and the book body begins)."""
    for contents in _CONTENTS_RE.finditer(content):
        entries: list[str] = []
        seen: set[str] = set()
        first_header: tuple[int, int] | None = None  # (entries so far, offset)
        offset = contents.end()
        end = None
        for raw in content[offset:].splitlines(keepends=True):
            line_start = offset
            offset += len(raw)
            line = raw.strip()
            if not line:
                continue
            header = _HEADER_RE.match(line)
            text = header.group(1) if header else line
            if _is_prose(line):
                end = line_start
                break
            if header:
                # A header repeating an entry we already saw is the body starting
                # (e.g. the TOC lists "Preface", then the book's own "Preface" header).
                if _norm(text) in seen:
                    end = line_start
                    break
                if first_header is None:
                    first_header = (len(entries), line_start)
            entry = _clean_entry(text)
            if not entry or entry.isdigit():
                continue
            entries.append(entry)
            seen.add(_norm(entry))
        if end is None:
            # No clear end: fall back to the first header after the contents heading.
            if first_header:
                entries, end = entries[:first_header[0]], first_header[1]
            else:
                end = offset
        if len(entries) >= 3:
            return entries, end
    return [], 0


def extract_toc_titles(content: str) -> list[str]:
    return _scan_toc(content)[0]


def find_body_start(content: str) -> int:
    """Character offset where the book body begins (after the TOC); 0 if no TOC was found."""
    return _scan_toc(content)[1]


def _matches(entry: str, header: str, matcher: difflib.SequenceMatcher) -> bool:
    if entry == header:
        return True
    short, long_ = sorted((entry, header), key=len)
    # One side carries an extra subtitle / merged neighbouring entry.
    if len(short.split()) >= 3 and long_.startswith(short + " "):
        return True
    matcher.set_seq1(header)
    return (
        matcher.real_quick_ratio() >= 0.9
        and matcher.quick_ratio() >= 0.9
        and matcher.ratio() >= 0.9
    )


def match_toc_to_headers(content: str, toc_titles: list[str]) -> list[tuple[str, int]]:
    """Pair TOC entries with body headers; returns (entry, character offset) in book order.

    Uses a longest-common-subsequence alignment, so an entry with no header (or a header
    with no entry) is simply skipped instead of derailing every entry after it.
    """
    _, body_start = _scan_toc(content)
    headers = []
    for m in re.finditer(r"^#{1,6}[ \t]*(.+?)[ \t]*$", content, re.M):
        if m.start() >= body_start and _norm(m.group(1)):
            headers.append((m.start(), _norm(m.group(1))))
    entries = [_norm(t) for t in toc_titles]
    n, m_ = len(entries), len(headers)

    match = [[False] * m_ for _ in range(n)]
    for i, entry in enumerate(entries):
        if not entry:
            continue
        matcher = difflib.SequenceMatcher(None, autojunk=False)
        matcher.set_seq2(entry)
        for j, (_, header) in enumerate(headers):
            match[i][j] = _matches(entry, header, matcher)

    # lcs[i][j] = best number of ordered pairs using entries[i:] and headers[j:]
    lcs = [[0] * (m_ + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m_ - 1, -1, -1):
            lcs[i][j] = max(lcs[i + 1][j], lcs[i][j + 1], lcs[i + 1][j + 1] + 1 if match[i][j] else 0)

    boundaries = []
    i = j = 0
    while i < n and j < m_:
        if match[i][j] and lcs[i][j] == lcs[i + 1][j + 1] + 1:
            boundaries.append((toc_titles[i], headers[j][0]))  # earliest header wins ties
            i += 1
            j += 1
        elif lcs[i + 1][j] >= lcs[i][j + 1]:
            i += 1
        else:
            j += 1
    return boundaries
