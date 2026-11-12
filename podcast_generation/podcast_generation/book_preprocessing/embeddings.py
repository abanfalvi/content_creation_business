"""LangChain embeddings adapter around OpenRouter's embeddings endpoint."""
import os
import time

from langchain_core.embeddings import Embeddings
from openrouter import OpenRouter
from openrouter.errors import TooManyRequestsResponseError


EMBEDDING_MODEL = "sentence-transformers/all-minilm-l6-v2"


class OpenRouterEmbedding(Embeddings):
    """LangChain Embeddings adapter around OpenRouter's embeddings endpoint."""

    def __init__(self, model: str = EMBEDDING_MODEL, api_key: str | None = None, max_retries: int = 5):
        self.model = model
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.max_retries = max_retries

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        for attempt in range(self.max_retries):
            try:
                with OpenRouter(api_key=self.api_key) as open_router:
                    res = open_router.embeddings.generate(input=texts, model=self.model)
                break
            except TooManyRequestsResponseError as err:
                if attempt == self.max_retries - 1:
                    raise
                retry_after = err.raw_response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 2 ** (attempt + 1)
                print(f"Rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(delay)

        # `index` maps each embedding back to its position in `texts`,
        # since the API doesn't guarantee `data` preserves input order.
        ordered = sorted(res.data, key=lambda d: d.index)
        return [d.embedding for d in ordered]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
