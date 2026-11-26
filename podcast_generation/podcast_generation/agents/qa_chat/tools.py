import hashlib, uuid
from typing import Any, Iterable, Sequence, Literal

from langchain.tools import ToolRuntime, tool
from langchain_classic.retrievers import MergerRetriever
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, ToolMessage

from ...book_preprocessing.source_meta import book_file, read_meta
from ...book_preprocessing.store import summaries_vector_store, vector_store
from ...book_preprocessing.video import split_transcript, stamp_seconds, timestamp_url
from ...reranker import OpenRouterRerank
from ...services import preferences

TOP_N = 9

Key = tuple[Any, Any, Any]


def _ref(slug: str, chunk_idx: Any, kind: str) -> str:
    """Short id the model cites inline as [[ref]]; the UI turns it into a numbered badge.

    Stable and unique per passage: chunk_idx is only unique within a book, so a short hash of the book slug
    prefixes it, and summaries (which share the chunk's idx) get an "s" suffix.
    """
    book = hashlib.sha1(str(slug).encode("utf-8")).hexdigest()[:5]
    return f"{book}-{chunk_idx}" + ("s" if kind == "summary" else "")


def _watch_url(slug: str, seconds: Any) -> str:
    """Link to the moment of a video where a passage starts; empty for a book (its chunks carry no start time)."""
    if seconds is None:
        return ""
    url = read_meta(slug).get("url") or ""
    return timestamp_url(url, int(seconds)) if url else ""


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
        "url": _watch_url(slug, m.get("start_seconds")),
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


def _unindexed_slugs(runtime: ToolRuntime) -> list[str]:
    """Selected sources that have no search index: short transcripts, which are read whole."""
    selected = _selected_slugs(runtime)
    unindexed = ((runtime.config or {}).get("configurable") or {}).get("unindexed_slugs") or []
    return [s for s in selected if s in unindexed]


def _unindexed_note(slugs: list[str]) -> str:
    return (
        "These selected sources are short and have no search index, so a search cannot find anything in them. "
        "Read each one whole with read_full_source: " + ", ".join(f"'{s}'" for s in slugs) + "."
    ) if slugs else ""


def _passages(slug: str) -> list[dict]:
    """A transcript's paragraphs as citable passages, each stamped with the time its stretch of audio starts."""
    try:
        text = book_file(slug).read_text(encoding="utf-8")
    except OSError:
        return []
    meta = read_meta(slug)
    title, url = meta.get("title") or slug, meta.get("url") or ""
    return [
        {"ref": _ref(slug, i, "chunk"), "chunk_idx": i, "slug": slug, "title": title, "chapter": f"from {stamp}",
         "kind": "chunk", "context": "", "text": body, "url": timestamp_url(url, stamp_seconds(stamp)) if url else ""}
        for i, (stamp, body) in enumerate(split_transcript(text), start=1)
    ]


def _search(search: Any, slugs: list[str], unindexed: list[str]) -> tuple[str, list[dict]]:
    """Run a search over the indexed sources only, and tell the model about the ones it has to read whole instead."""
    note = _unindexed_note(unindexed)
    indexed = [s for s in slugs if s not in unindexed]
    if not indexed:
        return note, []
    text, hits = _render(*search(indexed))
    return (f"{note}\n\n{text}" if note else text), hits


class QAChatAgentTools:

    @tool(response_format="content_and_artifact")
    @staticmethod
    def semantic_search_sources(query: str, runtime: ToolRuntime) -> tuple[str, list[dict]]:
        """Search semantically the user's selected sources for passages relevant to the query. Returns excerpts with their book and chapter."""
        slugs = _selected_slugs(runtime)
        if not slugs:
            return NO_SOURCES, []
        return _search(lambda indexed: _search_chunks(indexed, query, _seen(runtime)), slugs, _unindexed_slugs(runtime))

    @tool(response_format="content_and_artifact")
    @staticmethod
    def keyword_search_sources(query: str, keywords: list[str], runtime: ToolRuntime) -> tuple[str, list[dict]]:
        """Search by keyword the user's selected sources for passages relevant to the query. Returns excerpts with their book and chapter."""
        slugs = _selected_slugs(runtime)
        if not slugs:
            return NO_SOURCES, []
        if not any(k.strip() for k in keywords):
            return "Provide at least one keyword.", []
        return _search(lambda indexed: _keyword_search(indexed, query, keywords, _seen(runtime)), slugs, _unindexed_slugs(runtime))

    @tool(response_format="content_and_artifact")
    @staticmethod
    def read_full_source(slug: str, runtime: ToolRuntime) -> tuple[str, list[dict]]:
        """Read a whole short source (the transcript of a video) that has no search index. Use it only for the sources the search tools name, and give the source's slug. Returns every passage with its reference and the time its stretch of audio starts."""
        readable = _unindexed_slugs(runtime)
        if slug not in readable:
            return (f"'{slug}' cannot be read in full. " + (f"Readable sources: {', '.join(readable)}." if readable else "No selected source can be read in full; use the search tools.")), []
        seen = _seen(runtime)
        passages = [p for p in _passages(slug) if _key(p) not in seen]
        if not passages:
            return "This source was already read in full earlier in this conversation. Use that earlier result.", []
        body = "\n\n".join(f"[[{p['ref']}]] ({p['chapter']}) {p['text']}" for p in passages)
        return f"Full transcript of {passages[0]['title']} ({len(passages)} passages):\n\n{body}", passages

    @tool
    @staticmethod
    def update_user_preference(
        attribute: Literal["answer_length", "tone", "format", "jargon_level", "detail_level",
                           "audience", "language", "quote_policy", "other"],
        value: str,
        scope: Literal["notebook", "global"],
        signal: Literal["explicit", "implicit"],
        evidence: str,            # the user's wording that supports it
        is_correction: bool,      # "no, shorter", "I said X not Y"
        runtime: ToolRuntime,
        key: str = "",
    ) -> str:
        """Save how the user wants answers written, so it applies in later turns and chats. `evidence` must be words the user wrote in this conversation. For attribute "other", `key` is required: a short snake_case name for what the preference is about (for example "emoji_use"); each key is remembered separately."""
        name = preferences.resolve_attribute(attribute, key)
        if name is None:
            return "Not saved: attribute 'other' needs a short `key` naming what the preference is about, for example 'emoji_use'."
        conf = (runtime.config or {}).get("configurable") or {}
        said = " ".join(str(m.content) for m in (runtime.state or {}).get("messages", []) if isinstance(m, HumanMessage)).lower()
        if not evidence.strip() or evidence.strip().lower() not in said:
            return "Not saved: `evidence` must be words the user wrote in this conversation."
        problem = preferences.record(conf.get("notebook_id", ""), conf.get("session_id", ""), name, value, scope, signal, evidence, is_correction)
        return problem or ("Updated user preference." if is_correction else "Saved user preference.")

    @tool
    @staticmethod
    def forget_user_preference(
        attribute: Literal["answer_length", "tone", "format", "jargon_level", "detail_level",
                           "audience", "language", "quote_policy", "other"],
        scope: Literal["notebook", "global"],
        runtime: ToolRuntime,
        key: str = "",
    ) -> str:
        """Forget a saved preference the user no longer wants. For attribute "other", give the same `key` it was saved with."""
        name = preferences.resolve_attribute(attribute, key)
        if name is None:
            return "Nothing forgotten: attribute 'other' needs the `key` the preference was saved with."
        conf = (runtime.config or {}).get("configurable") or {}
        return preferences.retract(conf.get("notebook_id", ""), name, scope) or "User preference has been retracted."
