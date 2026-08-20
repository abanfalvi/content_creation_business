import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

conn = sqlite3.connect("./checkpoints/content_checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)

def get_book_path(book_title: str):
    symbols = [":", " ", ","]
    for symbol in symbols:
        book_title = book_title.replace(symbol, "_")
        book_title = book_title.replace("__", "_")
    title = book_title.lower()
    return title