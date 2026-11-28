"""Tools used by more than one content specialist."""
from langchain.tools import tool, ToolRuntime
from langchain_classic.retrievers.contextual_compression import (
    ContextualCompressionRetriever,
)
from typing import List, Dict

from podcast_generation.book_preprocessing.combined import members_of
from podcast_generation.book_preprocessing.source_meta import NOT_INDEXED_NOTE, is_indexed
from podcast_generation.book_preprocessing.store import vector_store
from podcast_generation.reranker import OpenRouterRerank
from .utils import get_book_path



class SharedContentTools:
    "Tools shared by the Expert Builder and Script Drafter agents"

    @tool
    @staticmethod
    def retrieve_info(query: str, runtime: ToolRuntime, title_book: str | None = None, chapter: str | None = None) -> List[Dict[str, str]] | str:
        "Retrieve information to understand the content of the source"
        book_title = runtime.state.get("book_title") or title_book
        if not book_title:
            return "[title_book] parameter should be provided because the title is not saved in state."
        slug = get_book_path(book_title)
        if not is_indexed(slug):  # an empty result would read as "the source does not say this"
            return NOT_INDEXED_NOTE.format(slug=slug)
        # Filter on the slug, so a title and its filename form are interchangeable. A combined source searches
        # every member that has chunks (short transcripts have none and are only in the text file).
        members = [m for m in members_of(slug) if m["indexed"]]
        clauses = [{"book_slug": {"$in": [m["slug"] for m in members]}} if members else {"book_slug": slug}]
        if chapter:
            clauses.append({"chapter": chapter})
        flt = clauses[0] if len(clauses) == 1 else {"$and": clauses}
        retriever = vector_store.as_retriever(search_kwargs={"k": 75, "filter": flt})
        compressor = OpenRouterRerank(top_n=6)
        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor, base_retriever=retriever
        )
        compressed_docs = compression_retriever.invoke(
            query
        )
        results = [{"Chunk content": doc.page_content, "Context summary": doc.metadata["context_summary"]} for doc in compressed_docs]
        if members:  # say which source each passage is from, so the claim is attributed to the right one
            for item, doc in zip(results, compressed_docs):
                item["Source"] = doc.metadata.get("Title", "")
        return results
