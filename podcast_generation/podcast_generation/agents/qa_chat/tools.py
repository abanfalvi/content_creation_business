import hashlib, uuid
from typing import Any, Iterable, Sequence

from langchain.tools import ToolRuntime, tool
from langchain_classic.retrievers import MergerRetriever
from langchain_core.documents import Document
from langchain_core.messages import ToolMessage

from ...book_preprocessing.store import summaries_vector_store, vector_store
from ...reranker import OpenRouterRerank

TOP_N = 9

Key = tuple[Any, Any, Any]


def _ref(slug: str, chunk_idx: Any, kind: str) -> str:
    """Short id the model cites inline as [[ref]]; the UI turns it into a numbered badge.

    Stable and unique per passage: chunk_idx is only unique within a book, so a short hash of the book slug
    prefixes it, and summaries (which share the chunk's idx) get an "s" suffix.
    """
    book = hashlib.sha1(str(slug).encode("utf-8")).hexdigest()[:5]
    return f"{book}-{chunk_idx}" + ("s" if kind == "summary" else "")


def _hit(d: Document) -> dict[str, Any]:
    m = d.metadata
    slug, chunk_idx = m.get("book_slug", ""), m.get("id", "")
    if not chunk_idx:
        chunk_idx = str(uuid.uuid4())[:3]
    # Only real chunks carry start_index; the neighbourhood summaries come from the other collection.
    kind = "chunk" if "start_index" in m else "summary"
    return {
        "ref": _ref(slug, chunk_idx, kind),
        "chunk_idx": chunk_idx,
        "slug": slug,
        "title": m.get("Title", ""),
        "chapter": m.get("chapter", "") or "",
        "kind": kind,
        "context": m.get("context_summary", "") or "",
        "text": d.page_content,
    }


def _key(h: dict[str, Any]) -> Key:
    # chunk_idx is the position inside one book, so it only identifies a chunk together with the book.
    return (h.get("slug"), h.get("chunk_idx"), h.get("kind"))


def _seen_keys(messages: Iterable[Any]) -> set[Key]:
    """Everything the agent has already been shown in this conversation."""
    return {
        _key(h)
        for m in messages
        if isinstance(m, ToolMessage) and isinstance(m.artifact, list)
        for h in m.artifact
    }


def _split(ranked: Iterable[Document], seen: set[Key], top_n: int) -> tuple[list[dict], list[dict]]:
    """Walk the ranking: the first `top_n` unseen hits are new; seen hits ranked above them are reported as such."""
    new: list[dict] = []
    old: list[dict] = []
    for d in ranked:
        h = _hit(d)
        if _key(h) in seen:
            old.append(h)
        elif len(new) < top_n:
            new.append(h)
        else:
            break
    return new, old


def _search_chunks(slugs: Sequence[str], query: str, seen: set[Key], top_n: int = TOP_N) -> tuple[list[dict], list[dict]]:
    """Semantic search over the chosen books (chunks and summaries), reranked. Returns (new, already_seen)."""
    where = {"book_slug": {"$in": list(slugs)}}
    merged = MergerRetriever(retrievers=[
        vector_store.as_retriever(search_kwargs={"k": 60, "filter": where}),
        summaries_vector_store.as_retriever(search_kwargs={"k": 30, "filter": where}),
    ])
    candidates = merged.invoke(query)
    # Ask the reranker for enough extra results that, after dropping the seen ones, `top_n` new ones remain.
    ranked = OpenRouterRerank(top_n=top_n + len(seen)).compress_documents(candidates, query)
    return _split(ranked, seen, top_n)


def _keyword_search(
    slugs: Sequence[str], query: str, keywords: Sequence[str], seen: set[Key], top_n: int = TOP_N
) -> tuple[list[dict], list[dict]]:
    """Chunks that literally contain one of the keywords, ordered by similarity to the query."""
    conditions = [{"$contains": k} for k in (k.strip() for k in keywords) if k]
    if not conditions:
        return [], []
    docs = vector_store.similarity_search(
        query,
        k=top_n + len(seen),
        filter={"book_slug": {"$in": list(slugs)}},  # type: ignore[arg-type]
        where_document=conditions[0] if len(conditions) == 1 else {"$or": conditions},
    )
    return _split(docs, seen, top_n)


def _label(h: dict[str, Any]) -> str:
    return h["title"] + (f" — {h['chapter']}" if h["chapter"] else "") + (" (summary)" if h["kind"] == "summary" else "")


def _render(new: list[dict], old: list[dict]) -> tuple[str, list[dict]]:
    """Tool output: only the new passages go to the model as text; the artifact keeps every hit for the UI's citations."""
    if not new and not old:
        return "No relevant passages were found in the selected sources.", []
    parts = []
    for h in new:
        body = "Summary of the surrounding text" if h["kind"] == "summary" else "Excerpt"
        parts.append(
            f"[[{h['ref']}]] {_label(h)}"
            + (f"\nContext: {h['context']}" if h["context"] else "")
            + f"\n{body}: {h['text']}"
        )
    if old:
        listed = "; ".join(dict.fromkeys(f"[[{h['ref']}]] {_label(h)}" for h in old))
        parts.append(f"Also relevant, but already retrieved earlier in this conversation (use your earlier results): {listed}")
    if not new:
        parts.insert(0, "No new passages were found for this search.")
    return "\n\n".join(parts), new + old


def _selected_slugs(runtime: ToolRuntime) -> list[str]:
    return ((runtime.config or {}).get("configurable") or {}).get("source_slugs") or []


def _seen(runtime: ToolRuntime) -> set[Key]:
    return _seen_keys((runtime.state or {}).get("messages", []))


NO_SOURCES = "No sources are selected. Ask the user to select at least one source."


class QAChatAgentTools:

    @tool(response_format="content_and_artifact")
    @staticmethod
    def semantic_search_sources(query: str, runtime: ToolRuntime) -> tuple[str, list[dict]]:
        """Search semantically the user's selected sources for passages relevant to the query. Returns excerpts with their book and chapter."""
        slugs = _selected_slugs(runtime)
        if not slugs:
            return NO_SOURCES, []
        return _render(*_search_chunks(slugs, query, _seen(runtime)))

    @tool(response_format="content_and_artifact")
    @staticmethod
    def keyword_search_sources(query: str, keywords: list[str], runtime: ToolRuntime) -> tuple[str, list[dict]]:
        """Search by keyword the user's selected sources for passages relevant to the query. Returns excerpts with their book and chapter."""
        slugs = _selected_slugs(runtime)
        if not slugs:
            return NO_SOURCES, []
        if not any(k.strip() for k in keywords):
            return "Provide at least one keyword.", []
        return _render(*_keyword_search(slugs, query, keywords, _seen(runtime)))
