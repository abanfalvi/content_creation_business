from langchain.tools import tool, ToolRuntime
from langchain_classic.retrievers.contextual_compression import (
    ContextualCompressionRetriever,
)
from langchain.agents import AgentState
from typing import List, Dict

from src.book_preprocessing.store import vector_store
from src.reranker import OpenRouterRerank
from src.agents.content_specialists.utils import get_book_path

def retrieve_info(query: str, title_book: str | None = None, chapter: str | None = None) -> Dict[str, str] | str:
    "Retrieve information to understand the content of the book"
    if title_book is None:
        return "[title_book] parameter should be provided because the title is not saved in state."
    clauses = [{"book_slug": get_book_path(title_book)}]
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
    # return {"Chunk content": compressed_docs[0].page_content, "Context summary": compressed_docs[0].metadata["context_summary"]}
    return compressed_docs[0]

if __name__ == "__main__":
    result = retrieve_info("How to start a career as an AI engineer?", "The Generative AI Career Masterplan")
    print(result)