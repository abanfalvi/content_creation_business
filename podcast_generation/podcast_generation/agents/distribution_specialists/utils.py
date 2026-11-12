import asyncio
from functools import cache

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from podcast_generation.settings import checkpoint_db


def _new_checkpointer() -> AsyncSqliteSaver:
    return AsyncSqliteSaver(aiosqlite.connect(checkpoint_db("distribution"), check_same_thread=False))


@cache
def get_checkpointer() -> AsyncSqliteSaver:
    """The distribution tier's async checkpointer, created on first use (shared afterwards).

    AsyncSqliteSaver.__init__ calls asyncio.get_running_loop(), so it can't be built as a
    bare object the way the sync tiers' SqliteSaver is — it needs a loop at construction.
    Inside a running loop (e.g. the async sub-agent builders) it is built directly;
    otherwise a throwaway loop is spun up just to satisfy that requirement. The captured
    loop reference is only used by AsyncSqliteSaver's *sync* wrapper methods (get_tuple,
    put, ...); this codebase only calls the async ones (aget_tuple, ainvoke, aget_state,
    ...), so the throwaway loop being closed afterwards is harmless.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        async def _build() -> AsyncSqliteSaver:
            return _new_checkpointer()
        return asyncio.run(_build())
    return _new_checkpointer()
