"""Tools used by more than one content specialist."""
from langchain.tools import tool
from langchain_cohere import CohereRerank
from langchain_classic.retrievers.contextual_compression import (
    ContextualCompressionRetriever,
)
from langchain_core.documents import Document
from typing import List
from dotenv import load_dotenv

from src.vector_db import vector_store

load_dotenv()


class SharedContentTools:
    "Tools shared by the Expert Builder and Script Drafter agents"

    @tool
    @staticmethod
    def retrieve_info(query: str) -> List[Document]:
        "Retrieve information to understand the content of the book"
        retriever = vector_store.as_retriever(k=25)
        compressor = CohereRerank(model="rerank-v4.0-fast", top_n=5) 
        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor, base_retriever=retriever
        )
        compressed_docs = compression_retriever.invoke(
            query
        )
        return [{"Chunk content": doc.page_content, "Context summary":doc.metadata["context_summary"]} for doc in compressed_docs]
