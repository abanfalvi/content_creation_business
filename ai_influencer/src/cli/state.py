"""Persists which orchestrator thread each named CLI session last used, so
returning to a session resumes its conversation (the orchestrator's own
checkpointer holds the actual message history/state per thread_id — this
just remembers which thread_id belongs to which session)."""
import json
import uuid
from datetime import datetime
from pathlib import Path

STATE_PATH = Path(".ai_influencer_cli/state.json")
DEFAULT_SESSION = "default"


def _load() -> dict:
    if not STATE_PATH.exists():
        return {"sessions": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _save(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def resolve_thread_id(session: str = DEFAULT_SESSION) -> str:
    """Return the thread_id last used for `session`, minting and persisting
    a new one on first use."""
    state = _load()
    thread_id = state["sessions"].get(session)
    if thread_id is None:
        thread_id = f"orchestrator::{session}"
        state["sessions"][session] = thread_id
        _save(state)
    return thread_id


def new_thread_id(session: str = DEFAULT_SESSION) -> str:
    """Mint and persist a fresh thread_id for `session`, abandoning its
    previous conversation (used for 'start a new conversation')."""
    state = _load()
    thread_id = f"orchestrator::{session}::{uuid.uuid4().hex[:8]}"
    state["sessions"][session] = thread_id
    _save(state)
    return thread_id


def new_auto_session() -> tuple[str, str]:
    """Mint a brand-new, uniquely-named session — used once per app launch —
    so every run starts its own conversation instead of resuming (and
    silently overwriting the thread pointer for) a fixed session name.
    Past sessions stay listed and reachable via /sessions."""
    state = _load()
    name = datetime.now().strftime("%Y%m%d_%H%M%S")
    if name in state["sessions"]:
        name = f"{name}_{uuid.uuid4().hex[:4]}"
    thread_id = new_thread_id(name)
    return name, thread_id


def all_sessions() -> dict[str, str]:
    """Every known session name -> thread_id, for display."""
    return dict(_load()["sessions"])


def delete_session(name: str) -> None:
    """Forget a named session's thread pointer. The orchestrator's own
    checkpointer still holds that thread_id's message history — this only
    removes the CLI's name -> thread_id mapping, so the session stops
    appearing in /sessions and reusing the name later starts fresh."""
    state = _load()
    state["sessions"].pop(name, None)
    _save(state)


def get_default_influencer() -> str | None:
    """The influencer slug new sessions should start with, if one was set."""
    return _load().get("default_influencer")


def set_default_influencer(slug: str) -> None:
    """Persist `slug` as the influencer new sessions auto-select."""
    state = _load()
    state["default_influencer"] = slug
    _save(state)
