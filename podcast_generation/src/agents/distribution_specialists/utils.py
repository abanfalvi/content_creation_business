import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

conn = sqlite3.connect("./checkpoints/distribution_checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)