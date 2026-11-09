"""Chroma vector store for ingested books, plus the batched loader."""
import time
from typing import List

from langchain_chroma import Chroma
from langchain_core.documents import Document
from tqdm import tqdm

from src.agents.content_specialists.utils import get_book_path

from .embeddings import OpenRouterEmbedding

embeddings = OpenRouterEmbedding()
vector_store = Chroma(
    collection_name="books_for_podcast",
    embedding_function=embeddings,
    persist_directory="./podcast_books_db",
)


def populate_vector_db(
    chunks: List[Document],
    vector_store: Chroma = vector_store,
    batch_size: int = 6,
    pause_seconds: float = 10,
) -> None:
    # Re-ingesting a book replaces its old chunks instead of duplicating them.
    for slug in sorted({c.metadata["book_slug"] for c in chunks}):
        vector_store.delete(where={"book_slug": slug})
    for idx in tqdm(range(0, len(chunks), batch_size)):
        batch = chunks[idx: idx + batch_size]
        vector_store.add_documents(batch)
        if idx + batch_size < len(chunks):
            time.sleep(pause_seconds)


def backfill_book_slugs(vector_store: Chroma = vector_store) -> int:
    """Add `book_slug` to chunks ingested before that field existed. Returns how many were updated."""
    got = vector_store.get(include=["metadatas"])
    ids, metadatas = [], []
    for id_, meta in zip(got["ids"], got["metadatas"]):
        if "book_slug" not in meta and meta.get("Title"):
            ids.append(id_)
            metadatas.append({**meta, "book_slug": get_book_path(meta["Title"])})
    for i in range(0, len(ids), 500):
        vector_store._collection.update(ids=ids[i:i + 500], metadatas=metadatas[i:i + 500])
    return len(ids)
