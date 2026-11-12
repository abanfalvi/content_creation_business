"""Tools used by more than one content specialist."""
from langchain.tools import tool, ToolRuntime
from langchain_classic.retrievers.contextual_compression import (
    ContextualCompressionRetriever,
)
from typing import List, Dict

from podcast_generation.book_preprocessing.store import vector_store
from podcast_generation.reranker import OpenRouterRerank
from .utils import get_book_path



class SharedContentTools:
    "Tools shared by the Expert Builder and Script Drafter agents"

    @tool
    @staticmethod
    def retrieve_info(query: str, runtime: ToolRuntime, title_book: str | None = None, chapter: str | None = None) -> List[Dict[str, str]] | str:
        "Retrieve information to understand the content of the book"
        book_title = runtime.state.get("book_title") or title_book
        if not book_title:
            return "[title_book] parameter should be provided because the title is not saved in state."
        # Filter on the slug, so a title and its filename form are interchangeable.
        clauses = [{"book_slug": get_book_path(book_title)}]
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
        return [{"Chunk content": doc.page_content, "Context summary": doc.metadata["context_summary"]} for doc in compressed_docs]
