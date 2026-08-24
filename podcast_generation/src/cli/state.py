import json
from pathlib import Path

STATE_PATH = Path(".podcast_cli/state.json")


def _load() -> dict:
    if not STATE_PATH.exists():
        return {"threads": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _save(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def resolve_thread_id(key: str, tier: str, thread_id: str | None) -> str:
    """Return `thread_id` if given explicitly; otherwise the thread_id last
    used for this `key` (usually a book title) + `tier` (content/production/
    distribution/book_selection); otherwise mint a stable new one. Persists
    whichever id is returned, so the next call without --thread-id resumes it."""
    state = _load()
    slot = f"{key}::{tier}"

    if thread_id is None:
        thread_id = state["threads"].get(slot)
    if thread_id is None:
        thread_id = slot.lower().replace(" ", "_")

    state["threads"][slot] = thread_id
    _save(state)
    return thread_id


def all_threads() -> dict[str, str]:
    """Every known slot -> thread_id, for display (e.g. the REPL's /status)."""
    return dict(_load()["threads"])
