import asyncio
import logging
import re
from contextlib import AsyncExitStack
from typing import AsyncIterator, Sequence

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openrouter import ChatOpenRouter
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from podcast_generation.agents.qa_chat.agent import build_qa_chat_agent
from podcast_generation.agents.qa_chat.agent import build_qa_chat_model as build_chat_model
from podcast_generation.agents.qa_chat.tools import slug_for_model
from podcast_generation.agents.models import CHAT_MODEL, CHAT_TITLE_MODEL
from podcast_generation.settings import checkpoint_db

from . import db, notebooks
from .context_usage import context_window, count_context_tokens
from . import preferences

log = logging.getLogger(__name__)


_MARKER = re.compile(r"\[\[([^\[\]]+)\]\]")

DEFAULT_SESSION_TITLE = "New chat"

_TITLE_PROMPT = (
    "You name chat conversations. Write a title for a new conversation from the user's first message below. "
    "At most 8 words, in the same language as the message. Reply with only the title: no quotes, no explanation, "
    "no trailing punctuation."
)


def build_title_model() -> ChatOpenRouter:
    """The cheap one-shot model that names a chat after its first message."""
    return ChatOpenRouter(model=CHAT_TITLE_MODEL, temperature=0.2, max_tokens=32, timeout=15_000)


def clean_title(text: str, max_words: int = 8) -> str:
    """A model reply as a title: surrounding quotes off, whitespace collapsed, at most `max_words` words."""
    return " ".join(text.strip().strip("\"'").split()[:max_words])


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


def _source_note(selected: Sequence[dict], unindexed: Sequence[str]) -> str:
    """A short system-prompt note naming the selected sources, so the model can fetch one it has not seen yet.

    The list is rebuilt every turn from the current selection, so it always matches what the user has ticked.
    """
    if not selected:
        return ""
    short = set(unindexed)
    lines = []
    for s in selected:
        kind = "video transcript" if s.get("kind") == "youtube" else "book"
        if s["slug"] in short:
            lines.append(f'- "{s["title"]}" ({kind}; no search index, so read it whole with read_full_source, slug: {slug_for_model(s["slug"])})')
        else:
            lines.append(f'- "{s["title"]}" ({kind})')
    return (
        "# Sources selected for this conversation\n"
        "The user has selected the sources below. When you need something from one that is not already in the "
        "conversation above, retrieve it with the search tools; read the short ones (marked below) whole with "
        "read_full_source using the given slug.\n" + "\n".join(lines)
    )


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
        self, session_id: str, message: str, selected_sources: Sequence[dict], notebook_id, unindexed_slugs: Sequence[str] = (),
    ) -> AsyncIterator[dict]:
        """Run one turn and yield UI events: status / token / sources / context / done / error.

        `selected_sources` are the ready source rows (slug, title, kind) the user has selected; `unindexed_slugs`
        are the subset with no search index (short transcripts), which the agent reads whole."""
        config = {"configurable": {
            "thread_id": _thread(session_id),
            "source_slugs": [s["slug"] for s in selected_sources],
            "unindexed_slugs": list(unindexed_slugs),
            "source_note": _source_note(selected_sources, unindexed_slugs),
            "notebook_id": notebook_id,
            "session_id": session_id,
            "preference_note": preferences.render_note(notebook_id)
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

def create_session(notebook_id: str, title: str = DEFAULT_SESSION_TITLE) -> dict:
    sid = db.new_id()
    ts = db.now()
    db.insert("sessions", {"id": sid, "notebook_id": notebook_id, "title": title, "created_at": ts, "updated_at": ts})
    notebooks.touch(notebook_id)
    return get_session(sid)


def get_session(session_id: str) -> dict | None:
    return db.one("SELECT * FROM sessions WHERE id = ?", [session_id])


def list_sessions(notebook_id: str) -> list[dict]:
    return db.query("SELECT * FROM sessions WHERE notebook_id = ? ORDER BY updated_at DESC", [notebook_id])


def touch_session(session_id: str) -> None:
    """Bump the session to the top of the list (and its notebook on the home page)."""
    db.update("sessions", "id", session_id, updated_at=db.now())
    session = get_session(session_id)
    if session:
        notebooks.touch(session["notebook_id"])


async def name_session(session_id: str, first_message: str) -> None:
    """Name a still-untitled chat after its first message, with one LLM call (at most 8 words).

    Meant to run in the background after a message is sent. A chat the user renamed keeps its name. If the
    call fails or comes back empty, the chat falls back to being named after the first message itself.
    """
    session = get_session(session_id)
    if session is None or session["title"] != DEFAULT_SESSION_TITLE:
        return
    title = ""
    try:
        reply = await build_title_model().ainvoke([SystemMessage(_TITLE_PROMPT), HumanMessage(first_message[:2000])])
        title = clean_title(str(reply.content))
    except Exception:  # noqa: BLE001 - naming is best-effort and must never break the chat
        log.warning("Could not name chat %s from its first message", session_id, exc_info=True)
    if not title:
        title = " ".join(first_message.split())[:60] or DEFAULT_SESSION_TITLE
    db.update("sessions", "id", session_id, title=title)


def rename_session(session_id: str, title: str) -> dict | None:
    """Give a chat a new title. Returns the updated session, or None if there is no such chat."""
    if get_session(session_id) is None:
        return None
    db.update("sessions", "id", session_id, title=title)
    return get_session(session_id)


def delete_session_row(session_id: str) -> None:
    db.execute("DELETE FROM sessions WHERE id = ?", [session_id])
