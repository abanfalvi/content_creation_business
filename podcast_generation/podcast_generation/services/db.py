"""Tiny SQLite store for the web app's own records.

Sources, chat sessions, generation/publish jobs and episodes live here. The agents'
conversation state is NOT here: it stays in the LangGraph checkpoint databases.
One shared connection guarded by a lock is plenty for a single-user app.
"""
import json
import sqlite3
import threading
import time
import uuid
from typing import Any, Iterable

from podcast_generation.settings import APP_DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    slug        TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    filename    TEXT NOT NULL,
    pdf_path    TEXT NOT NULL,
    pages       INTEGER NOT NULL,
    status      TEXT NOT NULL,            -- processing | ready | failed
    stage       TEXT NOT NULL DEFAULT '',
    error       TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,            -- generate | publish
    slug        TEXT NOT NULL,
    episode_id  TEXT,                     -- publish jobs: the episode being published
    status      TEXT NOT NULL,            -- running | awaiting_approval | done | failed
    stage       TEXT NOT NULL DEFAULT '', -- generate: content | production
    gate        TEXT,                     -- JSON: what the user is being asked to approve
    result      TEXT,                     -- JSON
    error       TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    id              TEXT PRIMARY KEY,
    slug            TEXT NOT NULL,
    title           TEXT NOT NULL,
    audio_path      TEXT NOT NULL,
    script_path     TEXT NOT NULL,
    job_id          TEXT NOT NULL,
    created_at      REAL NOT NULL,
    published_at    REAL,
    publish_result  TEXT
);
"""

_JSON_COLUMNS = {"gate", "result"}
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def init(path=None) -> None:
    """(Re)open the database and create the tables. Safe to call more than once."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = sqlite3.connect(path or APP_DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(_SCHEMA)
        _conn.commit()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> float:
    return time.time()


def _decode(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for key in _JSON_COLUMNS & out.keys():
        out[key] = json.loads(out[key]) if out[key] else None
    return out


def _encode(values: dict[str, Any]) -> dict[str, Any]:
    return {k: (json.dumps(v) if k in _JSON_COLUMNS and v is not None else v) for k, v in values.items()}


def query(sql: str, params: Iterable = ()) -> list[dict]:
    with _lock:
        assert _conn is not None, "db.init() has not been called"
        return [_decode(r) for r in _conn.execute(sql, tuple(params)).fetchall()]


def one(sql: str, params: Iterable = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable = ()) -> None:
    with _lock:
        assert _conn is not None, "db.init() has not been called"
        _conn.execute(sql, tuple(params))
        _conn.commit()


def insert(table: str, values: dict[str, Any]) -> None:
    values = _encode(values)
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", values.values())


def update(table: str, key_col: str, key: str, **values: Any) -> None:
    values = _encode(values)
    sets = ", ".join(f"{c} = ?" for c in values)
    execute(f"UPDATE {table} SET {sets} WHERE {key_col} = ?", [*values.values(), key])
