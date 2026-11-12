import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

from podcast_generation.settings import checkpoint_db

conn = sqlite3.connect(checkpoint_db("production"), check_same_thread=False)
checkpointer = SqliteSaver(conn)
