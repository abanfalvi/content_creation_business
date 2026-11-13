import json
from typing import Any, Iterator

from conftest import make_pdf, nb_url, wait_for
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from podcast_generation.services import chat, sources


class ScriptedModel(BaseChatModel):
    """Plays back a fixed list of AI messages, one per model call."""

    script: list[Any] = []
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        message = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


HITS = [
    {"slug": "deep_work", "title": "Deep Work", "chapter": "Rule 1", "context": "On focus.", "text": "Work deeply, without distraction."},
    {"slug": "deep_work", "title": "Deep Work", "chapter": "Rule 2", "context": "", "text": "Embrace boredom."},
]


def sse_events(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def add_ready_source(client, monkeypatch):
    async def fake(*a, **k):
        return "ok"

    monkeypatch.setattr(sources, "preprocess_book", fake)
    client.post(nb_url(client, "sources"), files=[("files", ("Deep_Work.pdf", make_pdf(), "application/pdf"))])
    wait_for(lambda: client.get(nb_url(client, "sources")).json()[0]["status"] == "ready")


def use_model(monkeypatch, *messages):
    searched = []

    def fake_search(slugs, query, top_n=6):
        searched.append((list(slugs), query))
        return HITS

    monkeypatch.setattr(chat, "search_chunks", fake_search)
    monkeypatch.setattr(chat, "build_chat_model", lambda: ScriptedModel(script=list(messages)))
    return searched


TOOL_CALL = AIMessage(content="", tool_calls=[{"name": "search_sources", "args": {"query": "focus"}, "id": "call_1"}])
ANSWER = AIMessage(content="Work without distraction [Deep Work, Rule 1].")


def test_sessions_can_be_created_listed_and_deleted(client):
    first = client.post(nb_url(client, "chat/sessions")).json()
    second = client.post(nb_url(client, "chat/sessions")).json()
    assert first["title"] == "New chat"
    assert {s["id"] for s in client.get(nb_url(client, "chat/sessions")).json()} == {first["id"], second["id"]}

    assert client.delete(f"/api/chat/sessions/{first['id']}").status_code == 204
    assert [s["id"] for s in client.get(nb_url(client, "chat/sessions")).json()] == [second["id"]]
    assert client.get(f"/api/chat/sessions/{first['id']}/messages").status_code == 404


def test_question_streams_an_answer_with_citations_and_is_remembered(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    searched = use_model(monkeypatch, TOOL_CALL, ANSWER)
    session = client.post(nb_url(client, "chat/sessions")).json()

    response = client.post(
        f"/api/chat/sessions/{session['id']}/messages",
        json={"message": "How do I focus?", "source_slugs": ["deep_work"]},
    )
    assert response.status_code == 200
    events = sse_events(response)
    kinds = [e["type"] for e in events]
    assert kinds[-1] == "done" and "error" not in kinds
    assert "".join(e["text"] for e in events if e["type"] == "token") == ANSWER.content
    assert searched == [(["deep_work"], "focus")]

    sources_event = next(e for e in events if e["type"] == "sources")
    assert [s["chapter"] for s in sources_event["sources"]] == ["Rule 1", "Rule 2"]

    history = client.get(f"/api/chat/sessions/{session['id']}/messages").json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["text"] == "How do I focus?"
    assert history[1]["text"] == ANSWER.content
    assert [s["title"] for s in history[1]["sources"]] == ["Deep Work", "Deep Work"]

    # the session is named after its first message
    assert client.get(nb_url(client, "chat/sessions")).json()[0]["title"] == "How do I focus?"


def test_asking_requires_a_ready_selected_source(client, monkeypatch):
    use_model(monkeypatch, ANSWER)
    session = client.post(nb_url(client, "chat/sessions")).json()
    response = client.post(f"/api/chat/sessions/{session['id']}/messages", json={"message": "Hi", "source_slugs": []})
    assert response.status_code == 422
    assert client.post("/api/chat/sessions/nope/messages", json={"message": "Hi", "source_slugs": ["x"]}).status_code == 404


def test_model_errors_reach_the_client_as_an_error_event(client, monkeypatch):
    add_ready_source(client, monkeypatch)

    def broken():
        raise RuntimeError("no API key")

    monkeypatch.setattr(chat, "build_chat_model", broken)
    session = client.post(nb_url(client, "chat/sessions")).json()
    events = sse_events(client.post(
        f"/api/chat/sessions/{session['id']}/messages", json={"message": "Hi", "source_slugs": ["deep_work"]}
    ))
    assert events == [{"type": "error", "message": "no API key"}]


class StreamingModel(ScriptedModel):
    """Streams its answer word by word, like a real chat model."""

    def _stream(self, messages, stop=None, run_manager=None, **kwargs) -> Iterator:
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        for word in ["Stream", "ing ", "works ", "once."]:
            yield ChatGenerationChunk(message=AIMessageChunk(content=word))


def test_tokens_of_a_streaming_model_arrive_incrementally_and_exactly_once(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    monkeypatch.setattr(chat, "build_chat_model", lambda: StreamingModel())
    session = client.post(nb_url(client, "chat/sessions")).json()
    events = sse_events(client.post(
        f"/api/chat/sessions/{session['id']}/messages", json={"message": "Hi", "source_slugs": ["deep_work"]}
    ))
    tokens = [e["text"] for e in events if e["type"] == "token"]
    assert len(tokens) > 1 and "".join(tokens) == "Streaming works once."
    assert events[-1] == {"type": "done"}
