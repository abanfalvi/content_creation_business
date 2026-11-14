import os
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent

# The project root holds .env, data/, checkpoints/ and the other runtime state.
# It is the folder above this package in a source checkout; set PODCAST_HOME to
# point somewhere else (e.g. when the package is installed rather than checked out).
PROJECT_ROOT = Path(os.environ.get("PODCAST_HOME") or PACKAGE_DIR.parent).resolve()

load_dotenv(PROJECT_ROOT / ".env")

# Opik reads its workspace/key from OPIK_* variables; the project name is fixed here.
os.environ.setdefault("OPIK_PROJECT_NAME", "podcast_generation")

# --- Runtime state (gitignored) --------------------------------------------------
DATA_DIR = PROJECT_ROOT / "data"                    # per-book working files: data/<slug>/...
CHECKPOINT_DIR = PROJECT_ROOT / "checkpoints"       # LangGraph SQLite checkpoints, one DB per tier
CHROMA_DIR = PROJECT_ROOT / "podcast_books_db"      # vector store of ingested books
TMP_DIR = PROJECT_ROOT / "tmp"                      # scratch space (per-turn TTS clips)
MCP_TOKEN_PATH = PROJECT_ROOT / ".mcp_tokens.json"  # cached OAuth tokens for the MCP servers
UPLOAD_DIR = PROJECT_ROOT / "uploads"               # source PDFs as uploaded in the web app
APP_DB_PATH = PROJECT_ROOT / "app.db"               # web app records: sources, chat sessions, jobs, episodes
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"  # built React app, served by the API when present

# E2B sandbox template the audio engineer agent edits in (Remotion pre-installed).
# Build it once with `uv run python -m podcast_generation.sandbox_template`.
E2B_TEMPLATE = os.environ.get("E2B_TEMPLATE", "podcast-remotion")

# --- Files that live inside the package --------------------------------------------
BOOK_LIST_PATH = PACKAGE_DIR / "book_list.json"     # the book wishlist (gitignored)
SKILLS_DIR = PACKAGE_DIR / "skills"                 # skill files, one folder per tier


def project_path(path: str | os.PathLike) -> Path:
    """Resolve a path that came from outside the code (the model, saved state, a CLI flag).

    Relative paths are taken relative to the project root, which is how the prompts
    describe them (`data/<slug>/...`); absolute paths are returned unchanged.
    """
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def checkpoint_db(tier: str) -> Path:
    """Path of a tier's checkpoint database (`content`, `production`).
    Creates the checkpoints folder if it is missing."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return CHECKPOINT_DIR / f"{tier}_checkpoints.db"


def require_env(name: str) -> str:
    """Return a required environment variable, or fail with a message that says where to set it."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Add it to {PROJECT_ROOT / '.env'} or the environment.")
    return value
