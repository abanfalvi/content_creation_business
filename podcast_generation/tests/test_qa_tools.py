from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from podcast_generation.agents.qa_chat.tools import _hit, _render, _seen_keys, _split


def doc(slug, idx, text="x", summary=False):
    meta = {"book_slug": slug, "Title": slug.title(), "id": idx, "chapter": "Ch 1"}
    if not summary:
        meta["start_index"] = 0
    return Document(page_content=text, metadata=meta)


def test_seen_keys_come_from_tool_artifacts_of_the_whole_thread():
    first = [_hit(doc("a", 1)), _hit(doc("a", 2))]
    messages = [
        HumanMessage("q1"),
        AIMessage("", tool_calls=[{"name": "semantic_search_sources", "args": {}, "id": "1"}]),
        ToolMessage("text", tool_call_id="1", artifact=first),
        AIMessage("answer"),
        HumanMessage("follow-up"),
    ]
    assert _seen_keys(messages) == {("a", 1, "chunk"), ("a", 2, "chunk")}
    assert _seen_keys([]) == set()


def test_same_index_in_another_book_or_kind_is_not_seen():
    seen = {("a", 1, "chunk")}
    new, old = _split([doc("b", 1), doc("a", 1, summary=True), doc("a", 1)], seen, top_n=8)
    assert [(h["slug"], h["kind"]) for h in new] == [("b", "chunk"), ("a", "summary")]
    assert [(h["slug"], h["kind"]) for h in old] == [("a", "chunk")]


def test_split_keeps_top_n_new_hits_and_only_reports_seen_ones_ranked_above_them():
    seen = {("a", 1, "chunk"), ("a", 9, "chunk")}
    ranked = [doc("a", 1), doc("a", 2), doc("a", 3), doc("a", 4), doc("a", 9)]
    new, old = _split(ranked, seen, top_n=2)
    assert [h["chunk_idx"] for h in new] == [2, 3]
    assert [h["chunk_idx"] for h in old] == [1]  # idx 9 ranks below the cut-off


def test_render_sends_only_new_text_to_the_model_but_keeps_every_hit_for_citations():
    new = [_hit(doc("a", 2, "fresh passage"))]
    old = [_hit(doc("a", 1, "old passage"))]
    text, artifact = _render(new, old)
    assert "fresh passage" in text and "old passage" not in text
    assert "already retrieved earlier" in text
    assert [h["chunk_idx"] for h in artifact] == [2, 1]


def test_render_when_nothing_is_new_says_so_and_still_returns_the_artifact():
    old = [_hit(doc("a", 1, "old passage"))]
    text, artifact = _render([], old)
    assert text.startswith("No new passages") and "old passage" not in text
    assert artifact == old
    assert _render([], []) == ("No relevant passages were found in the selected sources.", [])


def test_each_passage_gets_a_stable_unique_reference_to_cite():
    a, a_again, b, a_summary = _hit(doc("a", 1)), _hit(doc("a", 1)), _hit(doc("b", 1)), _hit(doc("a", 1, summary=True))
    assert a["ref"] == a_again["ref"]
    assert len({a["ref"], b["ref"], a_summary["ref"]}) == 3  # same idx in another book / as a summary differs
    text, _ = _render([a], [b])
    assert f"[[{a['ref']}]] A" in text and f"[[{b['ref']}]]" in text


def test_summary_hits_are_labelled():
    text, _ = _render([_hit(doc("a", 3, "neighbourhood recap", summary=True))], [])
    assert "Summary of the surrounding text: neighbourhood recap" in text
    assert "(summary)" in text
