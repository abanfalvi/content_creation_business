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

