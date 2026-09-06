import sqlite3, aiosqlite

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

_checkpointer_cm = None
checkpointer: AsyncSqliteSaver | None = None

async def get_checkpointer() -> AsyncSqliteSaver:
    global _checkpointer_cm, checkpointer
    if checkpointer is None:
        _checkpointer_cm = AsyncSqliteSaver.from_conn_string("./checkpoints/orchestration.db")
        checkpointer = await _checkpointer_cm.__aenter__()
    return checkpointer


async def close_checkpointer() -> None:
    """Release the checkpointer's aiosqlite connection. That connection runs
    its own non-daemon background thread, which otherwise keeps the whole
    process alive after the TUI exits — the terminal never gets its prompt
    back without this."""
    global _checkpointer_cm, checkpointer
    if _checkpointer_cm is not None:
        await _checkpointer_cm.__aexit__(None, None, None)
        _checkpointer_cm = None
        checkpointer = None

