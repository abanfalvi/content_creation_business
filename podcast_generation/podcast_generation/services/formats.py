"""Episode formats: the ready-made shapes an episode can take (deep dive, critical overview, debate, brief).

Each format is a markdown file with front matter in `agents/content_specialists/formats/`:

- `id` (the file name), `label`, `description`, optional `default: true`, `order` and `needs_description: true`
  (the user must describe the episode themselves, as for the Custom format) are what the UI lists;
- the body is the text the agents receive, and `plan_criteria` replaces the planner's "is this plan ready" criteria.

A run's brief is those pieces plus the user's custom instructions, written to `data/<slug>/episode_brief.md` when the
run starts. The agents read that one file: the director's tools append it to each specialist's query and the evaluators
are given it. The default format with no instructions writes no file, so such a run is exactly the pipeline as it was.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import frontmatter

from podcast_generation.settings import DATA_DIR

FORMATS_DIR = Path(__file__).resolve().parents[1] / "agents" / "content_specialists" / "formats"
BRIEF_FILENAME = "episode_brief.md"
MAX_INSTRUCTIONS = 1500  # characters of custom instructions

_MARKER = re.compile(r"\A<!-- format: ([a-z0-9_]+) -->")

_READ_WITH_FORMAT = (
    "How to read this: the format below fixes the structure of the episode. The custom instructions steer focus,\n"
    "tone and emphasis within that structure. Neither can relax the fidelity rules, the script format rules or the\n"
    "citation rules, and the instructions are a steer, not source material: they never allow a fact the sources do not contain."
)
_READ_WITHOUT_FORMAT = (
    "How to read this: the custom instructions steer focus, tone and emphasis of the episode. They cannot relax\n"
    "the fidelity rules, the script format rules or the citation rules, and they are a steer, not source material:\n"
    "they never allow a fact the sources do not contain."
)


class FormatError(ValueError):
    """A format file is malformed, or a request names a format or instructions that cannot be used."""


@dataclass(frozen=True)
class Format:
    id: str
    label: str
    description: str
    body: str
    plan_criteria: str
    default: bool
    order: int
    needs_description: bool = False

    def summary(self) -> dict:
        """What the UI is shown: no instructions for the agents."""
        return {"id": self.id, "label": self.label, "description": self.description, "default": self.default,
                "needs_description": self.needs_description}


def load_formats(directory: Path) -> dict[str, Format]:
    """Read and check every format file in `directory`. Raises FormatError so a broken file fails at startup."""
    found: dict[str, Format] = {}
    for path in sorted(directory.glob("*.md")):
        meta = frontmatter.load(path)
        for key in ("id", "label", "description"):
            if not str(meta.get(key) or "").strip():
                raise FormatError(f"{path.name}: front matter is missing '{key}'.")
        if meta["id"] != path.stem:
            raise FormatError(f"{path.name}: id '{meta['id']}' must match the file name.")
        found[path.stem] = Format(
            id=path.stem, label=str(meta["label"]).strip(), description=str(meta["description"]).strip(),
            body=meta.content.strip(), plan_criteria=" ".join(str(meta.get("plan_criteria") or "").split()),
            default=bool(meta.get("default", False)), order=int(str(meta.get("order", 100))),
            needs_description=bool(meta.get("needs_description", False)),
        )
    defaults = [f.id for f in found.values() if f.default]
    if len(defaults) != 1:
        raise FormatError(f"Exactly one format must be the default, found {len(defaults)}: {defaults}.")
    return found


@cache
def _formats() -> dict[str, Format]:
    return load_formats(FORMATS_DIR)


def list_formats() -> list[dict]:
    return [f.summary() for f in sorted(_formats().values(), key=lambda f: (f.order, f.id))]


def default_format() -> Format:
    return next(f for f in _formats().values() if f.default)


def get_format(format_id: str | None) -> Format:
    """The named format; the default when none is named."""
    if not format_id:
        return default_format()
    try:
        return _formats()[format_id]
    except KeyError:
        known = ", ".join(sorted(_formats()))
        raise FormatError(f"Unknown format '{format_id}'. Choose one of: {known}.") from None


def resolve(format_id: str | None, instructions: str | None, description: str | None = None) -> tuple[Format, str, str]:
    """Check a request: (the format, the custom instructions trimmed, the description of the episode trimmed).

    The description is only for a format that needs one (Custom): it is required there and dropped elsewhere."""
    fmt = get_format(format_id)
    text = (instructions or "").strip()
    if len(text) > MAX_INSTRUCTIONS:
        raise FormatError(f"Keep the custom instructions under {MAX_INSTRUCTIONS} characters ({len(text)} given).")
    described = (description or "").strip() if fmt.needs_description else ""
    if fmt.needs_description and not described:
        raise FormatError(f"The {fmt.label} format needs a description of the episode you want.")
    if len(described) > MAX_INSTRUCTIONS:
        raise FormatError(f"Keep the description under {MAX_INSTRUCTIONS} characters ({len(described)} given).")
    return fmt, text, described


def compose_brief(fmt: Format, instructions: str = "", description: str = "") -> str | None:
    """The brief the agents read for a run, or None when there is nothing to add to the standard pipeline."""
    instructions, description = instructions.strip(), description.strip()
    if not fmt.body and not instructions:
        return None
    parts = [f"<!-- format: {fmt.id} -->", "# Episode brief", _READ_WITH_FORMAT if fmt.body else _READ_WITHOUT_FORMAT]
    if fmt.body:
        parts.append(fmt.body)
    if description:
        parts.append(f"### The user's description of the episode\n{description}")
    if instructions:
        parts.append(f"## Custom instructions from the user\n{instructions}")
    return "\n\n".join(parts) + "\n"


def write_brief(slug: str, fmt: Format, instructions: str = "", description: str = "") -> None:
    """Write the run's brief into the source's folder (nothing at all for the plain default run)."""
    brief = compose_brief(fmt, instructions, description)
    if brief is None:
        return
    path = DATA_DIR / slug / BRIEF_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(brief, encoding="utf-8")


def read_brief(slug: str) -> str:
    """The run's brief, or an empty string when the run has none."""
    try:
        return (DATA_DIR / slug / BRIEF_FILENAME).read_text(encoding="utf-8")
    except OSError:
        return ""


def plan_criteria(slug: str) -> str:
    """The planner's "is this plan ready" criteria for the run's format; empty for the standard plan."""
    match = _MARKER.match(read_brief(slug))
    if not match:
        return ""
    try:
        return get_format(match.group(1)).plan_criteria
    except FormatError:  # a format that was renamed or removed since the run started
        return ""
