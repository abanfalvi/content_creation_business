import json
from typing import Any, Iterator

from conftest import make_pdf, nb_url, wait_for
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from podcast_generation.agents.qa_chat import tools as qa_tools
from podcast_generation.services import chat, preferences, sources


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
    {"ref": "r1", "chunk_idx": 1, "kind": "chunk", "slug": "deep_work", "title": "Deep Work", "chapter": "Rule 1", "context": "On focus.", "text": "Work deeply, without distraction."},
    {"ref": "r2", "chunk_idx": 2, "kind": "chunk", "slug": "deep_work", "title": "Deep Work", "chapter": "Rule 2", "context": "", "text": "Embrace boredom."},
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

    def fake_search(slugs, query, seen, top_n=8):
        searched.append((list(slugs), query))
        return HITS, []

    monkeypatch.setattr(qa_tools, "_search_chunks", fake_search)
    monkeypatch.setattr(chat, "build_chat_model", lambda: ScriptedModel(script=list(messages)))
    monkeypatch.setattr(chat, "build_title_model", lambda: ScriptedModel(script=[AIMessage(content="Chat title")]))
    return searched


TOOL_CALL = AIMessage(content="", tool_calls=[{"name": "semantic_search_sources", "args": {"query": "focus"}, "id": "call_1"}])
ANSWER = AIMessage(content="Work without distraction [[r1]].")


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
    assert [(s["ref"], s["chapter"], s["text"]) for s in sources_event["sources"]] == [("r1", "Rule 1", HITS[0]["text"])]
    assert events[-2]["type"] == "sources"  # the authoritative list comes last, right before done

    history = client.get(f"/api/chat/sessions/{session['id']}/messages").json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["text"] == "How do I focus?"
    assert history[1]["text"] == ANSWER.content
    assert [s["ref"] for s in history[1]["sources"]] == ["r1"]  # only what the answer cites, not everything retrieved

    # the first message names the chat, via the title model (runs in the background)
    def named_title():
        row = next(s for s in client.get(nb_url(client, "chat/sessions")).json() if s["id"] == session["id"])
        return row["title"] if row["title"] != "New chat" else None
    assert wait_for(named_title) == "Chat title"


def titled(client, session_id):
    """Poll the session's title until the background naming call has written one."""
    def named():
        row = next(s for s in client.get(nb_url(client, "chat/sessions")).json() if s["id"] == session_id)
        return row["title"] if row["title"] != "New chat" else None
    return wait_for(named)


def test_the_first_message_names_the_chat_with_an_llm_title_of_at_most_8_words(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    use_model(monkeypatch, ANSWER)
    seen: list[str] = []

    class TitleRecorder(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.extend(str(m.content) for m in messages)
            return super()._generate(messages, stop, run_manager, **kwargs)

    long_title = '"How to stay focused and productive every single work day"'  # 10 words, quoted
    monkeypatch.setattr(chat, "build_title_model", lambda: TitleRecorder(script=[AIMessage(content=long_title)]))
    session = client.post(nb_url(client, "chat/sessions")).json()
    message = "How can I focus better while reading Deep Work?"
    events = sse_events(client.post(
        f"/api/chat/sessions/{session['id']}/messages", json={"message": message, "source_slugs": ["deep_work"]}
    ))
    assert events[-1]["type"] == "done"

    # the title model was asked about the user's first message, and its answer became the title:
    # quotes stripped, capped at 8 words
    assert message in seen[-1]
    assert titled(client, session["id"]) == "How to stay focused and productive every single"

    # a later message does not rename the chat
    sse_events(client.post(
        f"/api/chat/sessions/{session['id']}/messages", json={"message": "And boredom?", "source_slugs": ["deep_work"]}
    ))
    row = next(s for s in client.get(nb_url(client, "chat/sessions")).json() if s["id"] == session["id"])
    assert row["title"] == "How to stay focused and productive every single"


def test_a_failing_title_call_falls_back_to_the_first_message(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    use_model(monkeypatch, ANSWER)

    def broken_title():
        raise RuntimeError("no API key")

    monkeypatch.setattr(chat, "build_title_model", broken_title)
    session = client.post(nb_url(client, "chat/sessions")).json()
    sse_events(client.post(
        f"/api/chat/sessions/{session['id']}/messages",
        json={"message": "How do I focus?\nReally?", "source_slugs": ["deep_work"]},
    ))
    assert titled(client, session["id"]) == "How do I focus? Really?"


def test_a_follow_up_can_cite_passages_from_an_earlier_turn_and_invented_refs_are_dropped(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    follow_up = AIMessage(content="More on boredom [[r2]], and something made up [[nope]].")
    use_model(monkeypatch, TOOL_CALL, ANSWER, follow_up)
    session = client.post(nb_url(client, "chat/sessions")).json()
    url = f"/api/chat/sessions/{session['id']}/messages"
    body = {"message": "How do I focus?", "source_slugs": ["deep_work"]}
    client.post(url, json=body)

    events = sse_events(client.post(url, json={**body, "message": "And boredom?"}))
    assert [s["ref"] for s in next(e for e in events if e["type"] == "sources")["sources"]] == ["r2"]
    assert [s["ref"] for s in events[-2]["sources"]] == ["r2"]

    history = client.get(f"/api/chat/sessions/{session['id']}/messages").json()
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    assert [s["ref"] for s in history[3]["sources"]] == ["r2"]


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
    monkeypatch.setattr(chat, "build_title_model", lambda: ScriptedModel(script=[AIMessage(content="Hi chat")]))
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


def test_context_usage_is_streamed_and_available_for_an_existing_chat(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    use_model(monkeypatch, AIMessage(content="Short answer.", usage_metadata={"input_tokens": 900, "output_tokens": 100, "total_tokens": 1000}))
    session = client.post(nb_url(client, "chat/sessions")).json()
    url = f"/api/chat/sessions/{session['id']}"

    assert client.get(f"{url}/context").json() == {"used": 0, "window": 100_000}  # nothing said yet

    events = sse_events(client.post(f"{url}/messages", json={"message": "Hi", "source_slugs": ["deep_work"]}))
    context = next(e for e in events if e["type"] == "context")
    assert (context["used"], context["window"]) == (1000, 100_000)
    assert client.get(f"{url}/context").json() == {"used": 1000, "window": 100_000}
    assert client.get("/api/chat/sessions/nope/context").status_code == 404


def test_context_tokens_use_the_reported_total_plus_an_estimate_for_what_came_after():
    from langchain_core.messages import HumanMessage

    from podcast_generation.services.context_usage import count_context_tokens

    reply = AIMessage(content="x", usage_metadata={"input_tokens": 90, "output_tokens": 10, "total_tokens": 100})
    assert count_context_tokens([HumanMessage("hi"), reply]) == 100
    assert count_context_tokens([HumanMessage("hi"), reply, HumanMessage("a" * 40)]) == 110  # 40 chars ~ 10 tokens
    assert count_context_tokens([HumanMessage("a" * 40)]) == 10  # no report: estimate everything
    assert count_context_tokens([]) == 0


def test_source_note_names_each_selected_source_and_the_slug_of_short_ones():
    selected = [
        {"slug": "deep_work", "title": "Deep Work", "kind": "pdf"},
        {"slug": "a_talk", "title": "A Talk", "kind": "youtube"},
    ]
    note = chat._source_note(selected, unindexed=["a_talk"])
    assert "Sources selected for this conversation" in note
    assert '"Deep Work"' in note and '"A Talk"' in note
    assert "slug: a_talk" in note and "read_full_source" in note  # the short one is readable whole, under its own slug
    assert "slug: deep_work" not in note  # an indexed one is searched, not read whole
    assert chat._source_note([], []) == ""


def test_the_model_is_told_which_sources_are_selected(client, monkeypatch):
    add_ready_source(client, monkeypatch)  # a ready "Deep Work" source
    seen_system: list[str] = []

    class Recorder(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if messages and isinstance(messages[0], SystemMessage):
                seen_system.append(str(messages[0].content))
            return super()._generate(messages, stop, run_manager, **kwargs)

    monkeypatch.setattr(chat, "build_chat_model", lambda: Recorder(script=[ANSWER]))
    session = client.post(nb_url(client, "chat/sessions")).json()
    events = sse_events(client.post(
        f"/api/chat/sessions/{session['id']}/messages",
        json={"message": "Hi", "source_slugs": ["deep_work"]},
    ))
    assert events[-1]["type"] == "done"
    assert seen_system and all("Sources selected for this conversation" in s for s in seen_system)
    assert any('"Deep Work"' in s for s in seen_system)



# --- preference memory ------------------------------------------------------------------------

def save_call(call_id="p1", **args) -> AIMessage:
    args = {"attribute": "answer_length", "value": "short", "scope": "notebook", "signal": "explicit",
            "evidence": "keep answers short", "is_correction": False, **args}
    return AIMessage(content="", tool_calls=[{"name": "update_user_preference", "args": args, "id": call_id}])


def ask(client, session, message, slugs=("deep_work",)):
    return sse_events(client.post(f"/api/chat/sessions/{session['id']}/messages", json={"message": message, "source_slugs": list(slugs)}))


def prefs_of(client) -> dict[str, dict]:
    return {p["attribute"]: p for p in preferences.list_visible(client.nb)}


def test_saved_preferences_are_in_the_system_prompt_of_every_turn(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    preferences.record(client.nb, "s0", "answer_length", "two sentences at most", "notebook", "explicit", "short please", False)
    seen_system: list[str] = []

    class Recorder(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            seen_system.append(str(messages[0].content))
            return super()._generate(messages, stop, run_manager, **kwargs)

    monkeypatch.setattr(chat, "build_chat_model", lambda: Recorder(script=[ANSWER]))
    session = client.post(nb_url(client, "chat/sessions")).json()
    assert ask(client, session, "Hi")[-1]["type"] == "done"
    assert seen_system and all("# User preferences" in s and "two sentences at most" in s for s in seen_system)
    assert not any("function" in s and "render_note" in s for s in seen_system)  # the note's text, not the function object


def test_the_prompt_has_no_preference_section_when_nothing_is_saved(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    seen_system: list[str] = []

    class Recorder(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            seen_system.append(str(messages[0].content))
            return super()._generate(messages, stop, run_manager, **kwargs)

    monkeypatch.setattr(chat, "build_chat_model", lambda: Recorder(script=[ANSWER]))
    session = client.post(nb_url(client, "chat/sessions")).json()
    ask(client, session, "Hi")
    assert seen_system and not any("# User preferences" in s for s in seen_system)


def test_a_preference_saved_in_one_turn_shapes_the_next_one(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    seen_system: list[str] = []

    class Recorder(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            seen_system.append(str(messages[0].content))
            return super()._generate(messages, stop, run_manager, **kwargs)

    monkeypatch.setattr(chat, "build_chat_model", lambda: Recorder(script=[save_call(), AIMessage(content="Got it."), ANSWER]))
    session = client.post(nb_url(client, "chat/sessions")).json()
    ask(client, session, "keep answers short")
    assert not any("# User preferences" in s for s in seen_system)  # nothing was saved when the first turn began
    seen_system.clear()
    ask(client, session, "What is deep work?")
    assert seen_system and all("# User preferences" in s and "short" in s for s in seen_system)


def test_the_assistant_saves_a_preference_for_the_notebook_of_the_chat(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    use_model(monkeypatch, save_call(), AIMessage(content="Got it, I'll keep answers short."))
    session = client.post(nb_url(client, "chat/sessions")).json()
    events = ask(client, session, "Please keep answers short.")
    assert events[-1]["type"] == "done"
    pref = prefs_of(client)["answer_length"]
    assert (pref["value"], pref["scope"], pref["notebook_id"], pref["signal"]) == ("short", "notebook", client.nb, "explicit")
    assert pref["session_id"] == session["id"] and pref["evidence"] == "keep answers short"


def test_a_global_preference_saved_in_one_notebook_applies_in_another(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    use_model(monkeypatch, save_call(attribute="tone", value="formal", scope="global", evidence="always be formal"), ANSWER)
    session = client.post(nb_url(client, "chat/sessions")).json()
    ask(client, session, "From now on always be formal, in every notebook.")
    other = client.post("/api/notebooks", json={"title": "Other"}).json()["id"]
    assert {(p["attribute"], p["value"]) for p in client.get(f"/api/notebooks/{other}/preferences").json()} == {("tone", "formal")}


def test_a_correction_replaces_the_earlier_value_in_the_next_turn(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    use_model(
        monkeypatch,
        save_call("p1"), AIMessage(content="Noted."),
        save_call("p2", value="medium", evidence="not that short", is_correction=True), AIMessage(content="Updated."),
    )
    session = client.post(nb_url(client, "chat/sessions")).json()
    ask(client, session, "Keep answers short")
    ask(client, session, "No, not that short, a bit longer")
    assert prefs_of(client)["answer_length"]["value"] == "medium"
    assert len(db_rows()) == 2 and [r["status"] for r in db_rows()] == ["superseded", "active"]


def test_a_preference_is_not_saved_unless_the_user_actually_said_it(client, monkeypatch):
    """A passage from a book (or the model's own idea) must not be able to write to the user's memory."""
    add_ready_source(client, monkeypatch)
    use_model(monkeypatch, save_call(evidence="the user wants every answer in French"), AIMessage(content="Okay."))
    session = client.post(nb_url(client, "chat/sessions")).json()
    ask(client, session, "What is deep work?")
    assert prefs_of(client) == {}


def test_the_assistant_can_forget_a_saved_preference(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    preferences.record(client.nb, "s0", "tone", "formal", "notebook", "explicit", "be formal", False)
    forget = AIMessage(content="", tool_calls=[{"name": "forget_user_preference", "args": {"attribute": "tone", "scope": "notebook"}, "id": "f1"}])
    use_model(monkeypatch, forget, AIMessage(content="Forgotten."))
    session = client.post(nb_url(client, "chat/sessions")).json()
    ask(client, session, "Forget that I wanted a formal tone")
    assert prefs_of(client) == {}


def db_rows() -> list[dict]:
    from podcast_generation.services import db
    return db.query("SELECT * FROM preferences ORDER BY rowid")


# --- free-form ("other") preferences ----------------------------------------------------------

def test_two_free_form_preferences_with_different_keys_are_both_kept(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    use_model(
        monkeypatch,
        save_call("p1", attribute="other", key="emoji_use", value="none", evidence="no emojis"), AIMessage(content="Noted."),
        save_call("p2", attribute="other", key="Page Numbers", value="mention them", evidence="page numbers"), AIMessage(content="Noted."),
    )
    session = client.post(nb_url(client, "chat/sessions")).json()
    ask(client, session, "No emojis please")
    ask(client, session, "And always give page numbers")
    assert {a: p["value"] for a, p in prefs_of(client).items()} == {"other:emoji_use": "none", "other:page_numbers": "mention them"}


def test_the_same_key_again_replaces_the_value(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    use_model(
        monkeypatch,
        save_call("p1", attribute="other", key="emoji_use", value="none", evidence="no emojis"), AIMessage(content="Noted."),
        save_call("p2", attribute="other", key="emoji_use", value="a few", evidence="a few emojis", is_correction=True), AIMessage(content="Noted."),
    )
    session = client.post(nb_url(client, "chat/sessions")).json()
    ask(client, session, "No emojis please")
    ask(client, session, "Actually a few emojis are fine")
    assert {a: p["value"] for a, p in prefs_of(client).items()} == {"other:emoji_use": "a few"}


def test_an_other_preference_without_a_key_is_refused_and_the_model_is_told(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    use_model(monkeypatch, save_call(attribute="other", value="none", evidence="no emojis"), AIMessage(content="Okay."))
    session = client.post(nb_url(client, "chat/sessions")).json()
    ask(client, session, "No emojis please")
    assert prefs_of(client) == {}
    state = client.app.state.chat._agent.get_state({"configurable": {"thread_id": f"chat:{session['id']}"}})
    tool_replies = [m.content for m in state.values["messages"] if getattr(m, "type", "") == "tool"]
    assert any("needs a short `key`" in str(r) for r in tool_replies)


def test_the_assistant_forgets_a_free_form_preference_by_its_key(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    preferences.record(client.nb, "s0", "other:emoji_use", "none", "notebook", "explicit", "no emojis", False)
    preferences.record(client.nb, "s0", "other:page_numbers", "mention them", "notebook", "explicit", "page numbers", False)
    forget = AIMessage(content="", tool_calls=[{"name": "forget_user_preference", "args": {"attribute": "other", "key": "emoji_use", "scope": "notebook"}, "id": "f1"}])
    use_model(monkeypatch, forget, AIMessage(content="Forgotten."))
    session = client.post(nb_url(client, "chat/sessions")).json()
    ask(client, session, "Forget the emoji rule")
    assert set(prefs_of(client)) == {"other:page_numbers"}
