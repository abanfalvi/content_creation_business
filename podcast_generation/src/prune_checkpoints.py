import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from datetime import datetime, timezone, timedelta

def prune_checkpoints(checkpoint_path: str):
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
    thread_ids = [thread_id[0] for thread_id in conn.execute("SELECT DISTINCT thread_id FROM checkpoints")]
    checkpointer = SqliteSaver(conn)

    for thread_id in thread_ids:
        tup = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
        created = datetime.fromisoformat(tup.checkpoint["ts"])
        if created < cutoff:
            checkpointer.delete_thread(thread_id)

    conn.execute("VACUUM")