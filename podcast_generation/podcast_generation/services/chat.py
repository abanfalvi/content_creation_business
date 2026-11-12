"""Chat: question answering over the sources the user has selected.

One LangGraph agent with a single `search_sources` tool. Which sources it may search is
decided per request (`source_slugs` in the run config), so the same conversation can be
continued with a different selection. Conversation history lives in the `chat` checkpoint
database; `sessions` in the app database only holds the list shown in the UI.
"""
import asyncio
import logging
from contextlib import AsyncExitStack
from typing import AsyncIterator, Sequence

from langchain.agents import create_agent
from langchain.tools import ToolRuntime, tool
from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openrouter import ChatOpenRouter
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from podcast_generation.agents.models import CHAT_MODEL
from podcast_generation.book_preprocessing.store import vector_store
from podcast_generation.reranker import OpenRouterRerank
from podcast_generation.settings import checkpoint_db

from . import db

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the research assistant of Level Up Lab, a podcast studio that turns books into episodes.
You answer the user's questions about the books they have selected as sources.

- Ground every answer in the sources. Call `search_sources` before answering anything about their content;
  call it again with a different query if the first results do not cover the question.
- Cite what you use inline as [Book title, Chapter] (leave the chapter out if it is unknown).
- If the sources do not contain the answer, say so plainly instead of guessing or using outside knowledge.
- Be concise and direct. Use short paragraphs or bullet points, and quote the author sparingly.
- If no sources are selected, tell the user to select at least one in the Sources panel.
"""


def search_chunks(slugs: Sequence[str], query: str, top_n: int = 6) -> list[dict]:
    """Semantic search over the chosen books, reranked. Blocking (network calls)."""
    retriever = vector_store.as_retriever(search_kwargs={"k": 40, "filter": {"book_slug": {"$in": list(slugs)}}})
    compressed = ContextualCompressionRetriever(
        base_compressor=OpenRouterRerank(top_n=top_n), base_retriever=retriever
    ).invoke(query)
    return [
        {
            "slug": d.metadata.get("book_slug", ""),
            "title": d.metadata.get("Title", ""),
            "chapter": d.metadata.get("chapter", "") or "",
            "context": d.metadata.get("context_summary", "") or "",
            "text": d.page_content,
        }
        for d in compressed
    ]


@tool(response_format="content_and_artifact")
def search_sources(query: str, runtime: ToolRuntime) -> tuple[str, list[dict]]:
    """Search the user's selected sources for passages relevant to the query. Returns excerpts with their book and chapter."""
    slugs = ((runtime.config or {}).get("configurable") or {}).get("source_slugs") or []
    if not slugs:
        return "No sources are selected. Ask the user to select at least one source.", []
    hits = search_chunks(slugs, query)
    if not hits:
        return "No relevant passages were found in the selected sources.", []
    text = "\n\n".join(
        f"[{i}] {h['title']}" + (f" — {h['chapter']}" if h["chapter"] else "")
        + (f"\nContext: {h['context']}" if h["context"] else "")
        + f"\nExcerpt: {h['text']}"
        for i, h in enumerate(hits, start=1)
    )
    return text, hits


def build_chat_model():
    return ChatOpenRouter(model=CHAT_MODEL, temperature=0.2)


def _citations(artifacts: list[list[dict]]) -> list[dict]:
    """Flatten tool artifacts into a de-duplicated list of cited passages."""
    seen, out = set(), []
    for hits in artifacts:
        for h in hits or []:
            key = (h.get("slug"), h.get("chapter"), h.get("text", "")[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": h.get("title", ""), "chapter": h.get("chapter", ""), "snippet": h.get("text", "")[:400]})
    return out


def _thread(session_id: str) -> str:
    return f"chat:{session_id}"


class ChatEngine:
    """Owns the chat agent and its checkpoint connection. Created lazily on first use."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._lock = asyncio.Lock()
        self._saver: AsyncSqliteSaver | None = None
        self._agent = None

    async def _ensure(self):
        async with self._lock:
            if self._agent is None:
                self._saver = await self._stack.enter_async_context(
                    AsyncSqliteSaver.from_conn_string(str(checkpoint_db("chat")))
                )
                await self._saver.setup()  # the tables are otherwise only created by the first checkpoint write
                self._agent = create_agent(
                    build_chat_model(), tools=[search_sources], system_prompt=SYSTEM_PROMPT, checkpointer=self._saver
                )
        return self._agent

    async def aclose(self) -> None:
        await self._stack.aclose()
        self._agent = self._saver = None

    async def stream(self, session_id: str, message: str, source_slugs: Sequence[str]) -> AsyncIterator[dict]:
        """Run one turn and yield UI events: status / token / sources / done / error."""
        config = {"configurable": {"thread_id": _thread(session_id), "source_slugs": list(source_slugs)}}
        try:
            agent = await self._ensure()
            async for chunk, meta in agent.astream({"messages": [HumanMessage(message)]}, config, stream_mode="messages"):
                if not isinstance(chunk, AIMessage) or meta.get("langgraph_node") == "tools":
                    continue
                calls = getattr(chunk, "tool_call_chunks", None) or chunk.tool_calls or []  # chunks stream them; whole messages carry tool_calls
                if any(tc.get("name") for tc in calls):
                    yield {"type": "status", "text": "Searching your sources…"}
                text = str(chunk.text)
                if text:
                    yield {"type": "token", "text": text}
            state = await agent.aget_state(config)
            yield {"type": "sources", "sources": _citations(_turn_artifacts(state.values.get("messages", [])))}
            yield {"type": "done"}
        except Exception as exc:  # noqa: BLE001 - reported to the client as an error event
            log.exception("Chat turn failed")
            yield {"type": "error", "message": str(exc) or type(exc).__name__}

    async def history(self, session_id: str) -> list[dict]:
        agent = await self._ensure()
        state = await agent.aget_state({"configurable": {"thread_id": _thread(session_id)}})
        out: list[dict] = []
        pending: list[list[dict]] = []
        for m in (state.values or {}).get("messages", []):
            if isinstance(m, HumanMessage):
                out.append({"role": "user", "text": str(m.text)})
                pending = []
            elif isinstance(m, ToolMessage):
                pending.append(m.artifact if isinstance(m.artifact, list) else [])
            elif isinstance(m, AIMessage) and not m.tool_calls and str(m.text):
                out.append({"role": "assistant", "text": str(m.text), "sources": _citations(pending)})
        return out

    async def delete_thread(self, session_id: str) -> None:
        await self._ensure()
        assert self._saver is not None
        await self._saver.adelete_thread(_thread(session_id))


def _turn_artifacts(messages: list) -> list[list[dict]]:
    """Tool artifacts produced since the most recent user message."""
    turn: list[list[dict]] = []
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, ToolMessage) and isinstance(m.artifact, list):
            turn.append(m.artifact)
    return list(reversed(turn))


# --- session list (app database) -------------------------------------------------------

def create_session(title: str = "New chat") -> dict:
    sid = db.new_id()
    ts = db.now()
    db.insert("sessions", {"id": sid, "title": title, "created_at": ts, "updated_at": ts})
    return get_session(sid)


def get_session(session_id: str) -> dict | None:
    return db.one("SELECT * FROM sessions WHERE id = ?", [session_id])


def list_sessions() -> list[dict]:
    return db.query("SELECT * FROM sessions ORDER BY updated_at DESC")


def touch_session(session_id: str, first_message: str | None = None) -> None:
    """Bump the session to the top of the list; name it after its first message."""
    fields: dict = {"updated_at": db.now()}
    session = get_session(session_id)
    if session and first_message and session["title"] == "New chat":
        fields["title"] = first_message.strip().replace("\n", " ")[:60] or "New chat"
    db.update("sessions", "id", session_id, **fields)


def delete_session_row(session_id: str) -> None:
    db.execute("DELETE FROM sessions WHERE id = ?", [session_id])
