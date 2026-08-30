# Create a Store to keep track of the pipeline progress

import os
from dotenv import load_dotenv
from langgraph.store.postgres import PostgresStore

load_dotenv()

DB_URI = os.environ["POSTGRES_URI"]


_store_cm = PostgresStore.from_conn_string(DB_URI)
shared_memory_store = _store_cm.__enter__()
shared_memory_store.setup() 
