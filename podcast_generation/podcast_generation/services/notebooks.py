"""Notebooks: the top-level container of the web app.

A notebook groups the sources the user has added, the chats about them and the episodes made from
them. Sources, chats, jobs and episodes each carry the `notebook_id` of the notebook they belong to.
"""
import logging
from pathlib import Path

from . import db

log = logging.getLogger(__name__)

DEFAULT_TITLE = "Untitled notebook"

# A notebook plus the numbers shown on its card on the home page.
_SELECT = """
SELECT n.*,
       (SELECT COUNT(*) FROM sources  WHERE notebook_id = n.id) AS source_count,
       (SELECT COUNT(*) FROM sessions WHERE notebook_id = n.id) AS chat_count,
       (SELECT COUNT(*) FROM episodes WHERE notebook_id = n.id) AS episode_count
FROM notebooks n
"""


class NotebookError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def list_notebooks() -> list[dict]:
    """Most recently used first (newest first when two were touched at the same instant)."""
    return db.query(_SELECT + " ORDER BY n.updated_at DESC, n.rowid DESC")


def get_notebook(notebook_id: str) -> dict | None:
    return db.one(_SELECT + " WHERE n.id = ?", [notebook_id])


def require_notebook(notebook_id: str) -> dict:
    notebook = get_notebook(notebook_id)
    if notebook is None:
        raise NotebookError("No such notebook.", 404)
    return notebook


def create_notebook(title: str | None = None) -> dict:
    notebook_id, ts = db.new_id(), db.now()
    db.insert("notebooks", {"id": notebook_id, "title": title or DEFAULT_TITLE, "created_at": ts, "updated_at": ts})
    return get_notebook(notebook_id)


def rename_notebook(notebook_id: str, title: str) -> dict:
    require_notebook(notebook_id)
    db.update("notebooks", "id", notebook_id, title=title, updated_at=db.now())
    return get_notebook(notebook_id)


def ensure_deletable(notebook_id: str) -> dict:
    """Raise unless the notebook exists and nothing in it is still being worked on."""
    notebook = require_notebook(notebook_id)
    if db.one("SELECT 1 AS busy FROM sources WHERE notebook_id = ? AND status = 'processing'", [notebook_id]):
        raise NotebookError("Some sources are still being processed. Wait for them to finish, then delete the notebook.", 409)
    if db.one("SELECT 1 AS busy FROM jobs WHERE notebook_id = ? AND status = 'running'", [notebook_id]):
        raise NotebookError("An episode is still being made. Wait for it to finish, then delete the notebook.", 409)
    return notebook


def delete_notebook(notebook_id: str) -> None:
    """Permanently remove a notebook and everything in it. Blocking: run it in a worker thread.

    Removes its sources (search index entries and the uploaded PDFs), chats, jobs and episodes (including their
    audio and script files). The chats' conversation history lives in the checkpoint database and is removed by the
    caller first (it needs the async chat engine). A job waiting for approval is simply dropped with its notebook.
    """
    from . import sources  # sources imports this module, so import it here

    ensure_deletable(notebook_id)
    for source in sources.list_sources(notebook_id):
        sources.delete_source(source["slug"])
    for episode in db.query("SELECT audio_path, script_path FROM episodes WHERE notebook_id = ?", [notebook_id]):
        for path in (episode["audio_path"], episode["script_path"]):
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                log.warning("Could not remove %s while deleting notebook %s", path, notebook_id)
    for table in ("episodes", "jobs", "sessions"):
        db.execute(f"DELETE FROM {table} WHERE notebook_id = ?", [notebook_id])
    db.execute("DELETE FROM notebooks WHERE id = ?", [notebook_id])


def touch(notebook_id: str | None) -> None:
    """Mark the notebook as just used, so it moves to the top of the home page."""
    if notebook_id:
        db.update("notebooks", "id", notebook_id, updated_at=db.now())
