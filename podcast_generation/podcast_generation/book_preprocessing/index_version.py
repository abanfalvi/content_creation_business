import hashlib

from .embeddings import EMBEDDING_MODEL

CHUNK_SIZE = 4096
CHUNKER_VERSION = "1"

INDEX_VERSION = f"{EMBEDDING_MODEL}|chunk-{CHUNK_SIZE}|v{CHUNKER_VERSION}"


def collection_name(base: str, version: str = INDEX_VERSION) -> str:
    """Chroma collection for `base` under an index version, e.g. books_for_podcast_3f2a9c1e."""
    return f"{base}_{hashlib.sha1(version.encode('utf-8')).hexdigest()[:8]}"
