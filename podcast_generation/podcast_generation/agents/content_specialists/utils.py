import re
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

from podcast_generation.settings import checkpoint_db

conn = sqlite3.connect(checkpoint_db("content"), check_same_thread=False)
checkpointer = SqliteSaver(conn)

def get_book_path(book_title: str):
    """Canonical book identity: the slug used for data/<slug>/ folders AND stored as
    `book_slug` metadata on every vector-DB chunk.

    Specialist state holds the human-readable title ("Contagious: Why Things Catch On");
    derive the slug with this function wherever one is needed. It is idempotent
    (a slug maps to itself), so a title and its slug are interchangeable inputs."""
    return re.sub(r"[:,\s]+", "_", book_title.strip()).lower()
