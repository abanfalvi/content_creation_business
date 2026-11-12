"""Shared Postgres store for lessons-learned traces.

The connection is opened on first use (`get_shared_store()`), not at import, so importing
the package works without a database.
"""
from functools import cache

from langgraph.store.postgres import PostgresStore

from podcast_generation.settings import require_env

# Keeps the connection pool's context manager alive for the process lifetime.
_store_cm = None


@cache
def get_shared_store() -> PostgresStore:
    global _store_cm
    # from_conn_string is a context manager; entering it once keeps the pool open and it
    # is never explicitly closed (same pattern as the SQLite checkpointers).
    _store_cm = PostgresStore.from_conn_string(require_env("POSTGRES_URI"))
    store = _store_cm.__enter__()
    store.setup()  # creates the tables; safe to call on every startup
    return store
