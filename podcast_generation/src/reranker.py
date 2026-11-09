"""LangChain document compressor backed by OpenRouter's rerank endpoint."""
import os
import time
from typing import Optional, Sequence

from dotenv import load_dotenv
from langchain_core.callbacks import Callbacks
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from openrouter import OpenRouter
from openrouter.errors import TooManyRequestsResponseError

load_dotenv()

RERANK_MODEL = "cohere/rerank-5-fast"


class OpenRouterRerank(BaseDocumentCompressor):
    """Drop-in replacement for CohereRerank that calls OpenRouter's /rerank.

    Works with ContextualCompressionRetriever as `base_compressor`.
    """

    model: str = RERANK_MODEL
    top_n: int = 5
    api_key: str = ""
    max_retries: int = 5

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        if not documents:
            return []

        api_key = self.api_key or os.getenv("OPENROUTER_API_KEY", "")
        texts = [doc.page_content for doc in documents]

        for attempt in range(self.max_retries):
            try:
                with OpenRouter(api_key=api_key) as open_router:
                    res = open_router.rerank.rerank(
                        model=self.model,
                        query=query,
                        documents=texts,
                        top_n=min(self.top_n, len(texts)),
                    )
                break
            except TooManyRequestsResponseError as err:
                if attempt == self.max_retries - 1:
                    raise
                retry_after = err.raw_response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 2 ** (attempt + 1)
                time.sleep(delay)

        # `index` maps each result back to the input list; results arrive
        # sorted by relevance, so the returned order is already best-first.
        reranked = []
        for result in res.results:
            doc = documents[result.index]
            reranked.append(
                Document(
                    page_content=doc.page_content,
                    metadata={**doc.metadata, "relevance_score": result.relevance_score},
                )
            )
        return reranked
