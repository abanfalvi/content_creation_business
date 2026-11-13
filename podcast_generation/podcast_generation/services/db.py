import json
import sqlite3
import threading
import time
import uuid
from typing import Any, Iterable

from podcast_generation.settings import APP_DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notebooks (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    slug        TEXT PRIMARY KEY,
    notebook_id TEXT,                     -- the notebook this source belongs to
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
    notebook_id TEXT,
    title       TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    notebook_id TEXT,
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
    notebook_id     TEXT,
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

# Tables whose rows belong to a notebook.
_NOTEBOOK_TABLES = ("sources", "sessions", "jobs", "episodes")
DEFAULT_NOTEBOOK_TITLE = "My notebook"

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
        _migrate(_conn)
        _conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring a database created before notebooks existed up to date.

    Adds the `notebook_id` columns and moves every existing source, chat, job and episode into one
    default notebook, so nothing the user already has disappears. Does nothing on a current database.
    """
    for table in _NOTEBOOK_TABLES:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "notebook_id" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN notebook_id TEXT")

    orphans = sum(
        conn.execute(f"SELECT COUNT(*) FROM {table} WHERE notebook_id IS NULL").fetchone()[0] for table in _NOTEBOOK_TABLES
    )
    if not orphans:
        return
    row = conn.execute("SELECT id FROM notebooks ORDER BY created_at LIMIT 1").fetchone()
    if row:
        notebook_id = row["id"]
    else:
        notebook_id, ts = new_id(), now()
        conn.execute(
            "INSERT INTO notebooks (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            [notebook_id, DEFAULT_NOTEBOOK_TITLE, ts, ts],
        )
    for table in ("sources", "sessions"):
        conn.execute(f"UPDATE {table} SET notebook_id = ? WHERE notebook_id IS NULL", [notebook_id])
    for table in ("jobs", "episodes"):  # follow their source; fall back for ones whose source was deleted
        conn.execute(
            f"UPDATE {table} SET notebook_id = (SELECT notebook_id FROM sources WHERE sources.slug = {table}.slug) "
            "WHERE notebook_id IS NULL"
        )
        conn.execute(f"UPDATE {table} SET notebook_id = ? WHERE notebook_id IS NULL", [notebook_id])


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
