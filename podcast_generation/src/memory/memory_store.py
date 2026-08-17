# Create a Store to keep track of the pipeline progress

import os
from dotenv import load_dotenv
from langgraph.store.postgres import PostgresStore

load_dotenv()

DB_URI = os.environ["POSTGRES_URI"]

# from_conn_string is a context manager; entering it once at module scope
# keeps the connection pool open for the process lifetime — same pattern
# your director.py files already use for SqliteSaver (conn opened once,
# never explicitly closed).
_store_cm = PostgresStore.from_conn_string(DB_URI)
shared_store = _store_cm.__enter__()
shared_store.setup()  # creates the tables; safe to call on every startup
