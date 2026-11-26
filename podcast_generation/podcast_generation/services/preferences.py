"""Preference memory: what the user told (or showed) the chat assistant about how they want to be answered.

One live value per (scope, notebook, attribute) slot. A newer explicit statement or a correction supersedes the live one,
an inferred value never overrides an explicit one, and a notebook value overrides a global one when answering."""
import logging
import re
import sqlite3
from typing import Any

from . import db

log = logging.getLogger(__name__)
IMPLICIT_MIN_HITS = 2

# The fixed vocabulary. Anything else is saved as "other" together with a short key naming what it is about,
# so that two unrelated "other" preferences do not compete for the same slot.
ATTRIBUTES = ("answer_length", "tone", "format", "jargon_level", "detail_level", "audience", "language", "quote_policy")
OTHER = "other"
_KEY_MAX = 40


def resolve_attribute(attribute: str, key: str = "") -> str | None:
    """The name a preference is stored under: the attribute itself, or "other:<key>" for a free-form one.

    The key is lower-cased to snake_case. A key that names a fixed attribute (the model tried "tone" as an
    "other" key) is saved as that attribute, so one topic never has two slots. None if "other" came without a usable key.
    """
    if attribute != OTHER:
        return attribute
    slug = re.sub(r"[^a-z0-9]+", "_", (key or "").lower()).strip("_")[:_KEY_MAX].strip("_")
    if not slug:
        return None
    return slug if slug in ATTRIBUTES else f"{OTHER}:{slug}"


def label(attribute: str) -> str:
    """What to call a stored attribute when showing it: the key for a free-form one, the name otherwise."""
    return attribute.split(":", 1)[1] if attribute.startswith(OTHER + ":") else attribute
_SLOT = "scope = ? AND COALESCE(notebook_id, '') = ? AND attribute = ? AND status = 'active'"


def _slot(notebook_id, scope, attribute):
    return [scope, "" if scope == "global" else notebook_id, attribute]


def _insert(notebook_id, session_id, attribute, value, scope, signal, evidence):
    new_id = db.new_id()
    return new_id, ("INSERT INTO preferences (id, scope, notebook_id, attribute, value, signal, evidence, session_id, hits, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'active', ?)",
                    [new_id, scope, None if scope == "global" else notebook_id, attribute, value, signal, evidence, session_id, db.now()])


def _replace(old, notebook_id, session_id, attribute, value, scope, signal, evidence):
    new_id, insert = _insert(notebook_id, session_id, attribute, value, scope, signal, evidence)
    db.execute_many([("UPDATE preferences SET status = 'superseded', superseded_by = ? WHERE id = ?", [new_id, old["id"]]), insert])


def record(notebook_id, session_id, attribute, value, scope, signal, evidence, correction) -> str | None:
    for _ in range(2):  # a racing writer can win the slot between our read and write: look again once
        old = db.one(f"SELECT * FROM preferences WHERE {_SLOT}", _slot(notebook_id, scope, attribute))
        try:
            if old is None:
                db.execute_many([_insert(notebook_id, session_id, attribute, value, scope, signal, evidence)[1]])
            elif signal == "explicit" or correction:
                _replace(old, notebook_id, session_id, attribute, value, scope, signal, evidence)
            elif old["signal"] == "explicit":
                return "Kept existing explicit preference. Inferred behaviour does not override what the user stated."
            elif old["value"] == value:
                db.update("preferences", "id", old["id"], hits=old["hits"] + 1)
            else:
                _replace(old, notebook_id, session_id, attribute, value, scope, signal, evidence)
            return None
        except sqlite3.IntegrityError:
            continue
    return "Could not save the preference; try again."


def retract(notebook_id, attribute, scope) -> None | str:
    old = db.one(f"SELECT * FROM preferences WHERE {_SLOT}", _slot(notebook_id, scope, attribute))
    if old is None:
        return "No saved preference was found for that attribute and scope."
    db.update("preferences", "id", old["id"], status="retracted")


def active_for(notebook_id) -> list[dict]:
    rows = db.query(
        "SELECT * FROM preferences WHERE status = 'active' AND (scope = 'global' OR notebook_id = ?) ORDER BY created_at, rowid",
        [notebook_id])
    best: dict[str, dict] = {}
    for r in rows:
        if r["signal"] == "implicit" and r["hits"] < IMPLICIT_MIN_HITS:
            continue
        have = best.get(r["attribute"])
        if have is None or (r["scope"] == "notebook" and have["scope"] == "global"):
            best[r["attribute"]] = r
    return list(best.values())


def _render_prompt_block(prefs: list[dict[str, Any]]) -> str:
    lines = [f"- {label(p['attribute'])}: {p['value']}" + (" (inferred, hold it loosely)" if p["signal"] == "implicit" else "") for p in prefs]
    return "# User preferences\nApply these when you answer:\n" + "\n".join(lines)


def render_note(notebook_id) -> str:
    prefs = active_for(notebook_id)
    return _render_prompt_block(prefs) if prefs else ""


def delete_for_notebook(notebook_id) -> None:
    db.execute("DELETE FROM preferences WHERE notebook_id = ?", [notebook_id])


def list_visible(notebook_id: str) -> list[dict]:
    return db.query("SELECT * FROM preferences WHERE status = 'active' AND (scope = 'global' OR notebook_id = ?) ORDER BY created_at DESC, rowid DESC", [notebook_id])


def remove(preference_id: str) -> bool:
    if db.one("SELECT 1 AS found FROM preferences WHERE id = ? AND status = 'active'", [preference_id]) is None:
        return False
    db.update("preferences", "id", preference_id, status="retracted")
    return True
