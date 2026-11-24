import asyncio
import logging
import re
from contextlib import AsyncExitStack
from typing import AsyncIterator, Sequence

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from podcast_generation.agents.qa_chat.agent import build_qa_chat_agent
from podcast_generation.agents.qa_chat.agent import build_qa_chat_model as build_chat_model
from podcast_generation.agents.models import CHAT_MODEL
from podcast_generation.settings import checkpoint_db

from . import db, notebooks
from .context_usage import context_window, count_context_tokens

log = logging.getLogger(__name__)


_MARKER = re.compile(r"\[\[([^\[\]]+)\]\]")


def _cited_refs(text: str) -> list[str]:
    """References cited in an answer as [[ref]] (or [[ref, ref]]), in order of first appearance."""
    refs = (r.strip() for m in _MARKER.finditer(text) for r in re.split(r"[,;]", m.group(1)))
    return list(dict.fromkeys(r for r in refs if r))


def _hits_by_ref(messages: list) -> dict[str, dict]:
    """Every passage the agent has retrieved in this thread so far, keyed by the reference it cites them with."""
    known: dict[str, dict] = {}
    for m in messages:
        if isinstance(m, ToolMessage) and isinstance(m.artifact, list):
            for h in m.artifact:
                if isinstance(h, dict) and h.get("ref"):
                    known.setdefault(h["ref"], {
                        "ref": h["ref"],
                        "kind": h.get("kind", "chunk"),
                        "title": h.get("title", ""),
                        "chapter": h.get("chapter", ""),
                        "text": h.get("text", ""),
                    })
    return known


def _cited_sources(text: str, known: dict[str, dict]) -> list[dict]:
    """The passages an answer cites, in citation order. Unknown (invented) references are dropped."""
    return [known[r] for r in _cited_refs(text) if r in known]


async def _usage(messages: list) -> dict:
    return {"used": count_context_tokens(messages), "window": await context_window(CHAT_MODEL)}


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
                self._agent = build_qa_chat_agent(build_chat_model(), self._saver)
        return self._agent

    async def aclose(self) -> None:
        await self._stack.aclose()
        self._agent = self._saver = None

    async def stream(
        self, session_id: str, message: str, source_slugs: Sequence[str], unindexed_slugs: Sequence[str] = (),
    ) -> AsyncIterator[dict]:
        """Run one turn and yield UI events: status / token / sources / context / done / error.

        `unindexed_slugs` are the selected sources that have no search index (short transcripts): the agent reads them whole."""
        config = {"configurable": {
            "thread_id": _thread(session_id), "source_slugs": list(source_slugs), "unindexed_slugs": list(unindexed_slugs),
        }}
        try:
            agent = await self._ensure()
            answer = ""  # everything streamed this turn, as the UI shows it
            known: dict[str, dict] = {}
            sent: set[str] = set()
            async for chunk, meta in agent.astream({"messages": [HumanMessage(message)]}, config, stream_mode="messages"):
                if not isinstance(chunk, AIMessage) or meta.get("langgraph_node") == "tools":
                    continue
                calls = getattr(chunk, "tool_call_chunks", None) or chunk.tool_calls or []  # chunks stream them; whole messages carry tool_calls
                if any(tc.get("name") for tc in calls):
                    yield {"type": "status", "text": "Searching your sources…"}
                text = str(chunk.text)
                if text:
                    answer += text
                    yield {"type": "token", "text": text}
                    # Send each cited passage as soon as its marker is complete, so the badge can be hovered while streaming.
                    fresh = [r for r in _cited_refs(answer) if r not in sent] if "]" in text else []
                    if fresh:
                        if any(r not in known for r in fresh):
                            known = _hits_by_ref((await agent.aget_state(config)).values.get("messages", []))
                        sent.update(fresh)
                        batch = [known[r] for r in fresh if r in known]
                        if batch:
                            yield {"type": "sources", "sources": batch}
            state = await agent.aget_state(config)
            messages = state.values.get("messages", [])
            yield {"type": "context", **await _usage(messages)}
            yield {"type": "sources", "sources": _cited_sources(answer, _hits_by_ref(messages))}  # the authoritative list, right before done
            yield {"type": "done"}
        except Exception as exc:  # noqa: BLE001 - reported to the client as an error event
            log.exception("Chat turn failed")
            yield {"type": "error", "message": str(exc) or type(exc).__name__}

    async def history(self, session_id: str) -> list[dict]:
        agent = await self._ensure()
        state = await agent.aget_state({"configurable": {"thread_id": _thread(session_id)}})
        out: list[dict] = []
        retrieved: list = []  # the thread so far: later answers may cite passages retrieved in earlier turns
        for m in (state.values or {}).get("messages", []):
            retrieved.append(m)
            if isinstance(m, HumanMessage):
                out.append({"role": "user", "text": str(m.text)})
            elif isinstance(m, AIMessage) and not m.tool_calls and str(m.text):
                out.append({"role": "assistant", "text": str(m.text), "sources": _cited_sources(str(m.text), _hits_by_ref(retrieved))})
        return out

    async def context_usage(self, session_id: str) -> dict:
        """Tokens the chat has used so far and the model's context window."""
        agent = await self._ensure()
        state = await agent.aget_state({"configurable": {"thread_id": _thread(session_id)}})
        return await _usage((state.values or {}).get("messages", []))

    async def delete_thread(self, session_id: str) -> None:
        await self._ensure()
        assert self._saver is not None
        await self._saver.adelete_thread(_thread(session_id))


# --- session list (app database) -------------------------------------------------------

def create_session(notebook_id: str, title: str = "New chat") -> dict:
    sid = db.new_id()
    ts = db.now()
    db.insert("sessions", {"id": sid, "notebook_id": notebook_id, "title": title, "created_at": ts, "updated_at": ts})
    notebooks.touch(notebook_id)
    return get_session(sid)


def get_session(session_id: str) -> dict | None:
    return db.one("SELECT * FROM sessions WHERE id = ?", [session_id])


def list_sessions(notebook_id: str) -> list[dict]:
    return db.query("SELECT * FROM sessions WHERE notebook_id = ? ORDER BY updated_at DESC", [notebook_id])


def touch_session(session_id: str, first_message: str | None = None) -> None:
    """Bump the session to the top of the list; name it after its first message (unless it was renamed)."""
    fields: dict = {"updated_at": db.now()}
    session = get_session(session_id)
    if session and first_message and session["title"] == "New chat":
        fields["title"] = first_message.strip().replace("\n", " ")[:60] or "New chat"
    db.update("sessions", "id", session_id, **fields)
    if session:
        notebooks.touch(session["notebook_id"])


def rename_session(session_id: str, title: str) -> dict | None:
    """Give a chat a new title. Returns the updated session, or None if there is no such chat."""
    if get_session(session_id) is None:
        return None
    db.update("sessions", "id", session_id, title=title)
    return get_session(session_id)


def delete_session_row(session_id: str) -> None:
    db.execute("DELETE FROM sessions WHERE id = ?", [session_id])
