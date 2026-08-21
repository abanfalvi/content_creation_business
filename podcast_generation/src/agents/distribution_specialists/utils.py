import sqlite3, aiosqlite
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

conn = aiosqlite.connect("./checkpoints/distribution_checkpoints.db", check_same_thread=False)
checkpointer = AsyncSqliteSaver(conn)