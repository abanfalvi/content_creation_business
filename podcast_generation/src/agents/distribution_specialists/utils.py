import asyncio

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


async def _build_checkpointer() -> AsyncSqliteSaver:
    # AsyncSqliteSaver.__init__ calls asyncio.get_running_loop(), so it can't
    # be constructed as a bare module-level object the way the sync tiers'
    # SqliteSaver is — it needs a loop present at construction time. Jupyter
    # always has one running, which is why this worked in the notebook; a
    # plain script/CLI process doesn't, so a throwaway loop is spun up here
    # just to satisfy that requirement. The captured loop reference is only
    # ever used by AsyncSqliteSaver's *sync* wrapper methods (get_tuple, put,
    # etc.) — this codebase only calls the async ones (aget_tuple, ainvoke,
    # aget_state, ...), so the loop being closed afterward is harmless.
    conn = aiosqlite.connect("./checkpoints/distribution_checkpoints.db", check_same_thread=False)
    return AsyncSqliteSaver(conn)


checkpointer = asyncio.run(_build_checkpointer())