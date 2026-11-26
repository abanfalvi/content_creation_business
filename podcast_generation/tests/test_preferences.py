"""Preference memory: the rules in services.preferences, the table behind them, and the API that lists them.

The service tests use a bare database (no app, no model). The API tests use the `client` fixture.
"""
import sqlite3

import pytest
from conftest import nb_url

from podcast_generation.services import db, preferences

NB, OTHER = "nb1", "nb2"


@pytest.fixture()
def prefs(tmp_path):
    """A fresh, empty database for the service tests."""
    db.init(tmp_path / "app.db")
    return preferences


def save(attribute="answer_length", value="short", *, notebook=NB, scope="notebook", signal="explicit",
         correction=False, evidence="keep it short", session="s1"):
    preferences.record(notebook, session, attribute, value, scope, signal, evidence, correction)


def rows(**where) -> list[dict]:
    clause = " AND ".join(f"{k} = ?" for k in where) or "1=1"
    return db.query(f"SELECT * FROM preferences WHERE {clause} ORDER BY rowid", list(where.values()))


def active(notebook=NB) -> dict[str, dict]:
    """The preferences in force in a notebook, by attribute."""
    return {p["attribute"]: p for p in preferences.active_for(notebook)}


# --- saving and superseding -------------------------------------------------------------------

def test_a_new_preference_is_saved_as_active(prefs):
    save()
    [row] = rows()
    assert (row["attribute"], row["value"], row["scope"], row["notebook_id"]) == ("answer_length", "short", "notebook", NB)
    assert (row["signal"], row["status"], row["evidence"], row["session_id"]) == ("explicit", "active", "keep it short", "s1")
    assert row["superseded_by"] is None and row["created_at"] > 0


def test_a_later_explicit_statement_replaces_the_earlier_one_and_links_to_it(prefs):
    save(value="short")
    save(value="detailed", evidence="more detail please")
    old, new = rows()
    assert (old["status"], old["superseded_by"]) == ("superseded", new["id"])
    assert (new["status"], new["value"]) == ("active", "detailed")
    assert active()["answer_length"]["value"] == "detailed"


def test_a_correction_supersedes_what_was_there_even_when_it_is_only_inferred(prefs):
    save(value="short", signal="implicit")
    save(value="medium", signal="implicit", correction=True, evidence="no, not that short")
    old, new = rows()
    assert (old["status"], old["superseded_by"]) == ("superseded", new["id"])
    assert new["value"] == "medium"


def test_an_inferred_preference_never_overrides_an_explicit_one(prefs):
    save(value="short", signal="explicit")
    result = preferences.record(NB, "s2", "answer_length", "long", "notebook", "implicit", "asked for more", False)
    [row] = rows()
    assert (row["value"], row["status"], row["signal"]) == ("short", "active", "explicit")
    assert "explicit" in str(result).lower()  # the model is told why nothing changed


def test_seeing_the_same_inferred_value_again_counts_a_hit_instead_of_adding_a_row(prefs):
    save(value="short", signal="implicit")
    save(value="short", signal="implicit", session="s2")
    [row] = rows()
    assert (row["hits"], row["status"]) == (2, "active")


def test_a_different_inferred_value_supersedes_the_earlier_inferred_one(prefs):
    save(value="short", signal="implicit")
    save(value="long", signal="implicit", session="s2")
    old, new = rows()
    assert (old["status"], old["superseded_by"], new["value"], new["hits"]) == ("superseded", new["id"], "long", 1)


def test_there_is_never_more_than_one_active_row_per_attribute_and_scope(prefs):
    for value in ("a", "b", "c"):
        save(value=value)
    assert len(rows(status="active")) == 1 and len(rows(status="superseded")) == 2
    save("tone", "formal")  # another attribute is its own slot
    assert len(rows(status="active")) == 2


def test_the_database_itself_refuses_a_second_active_row_in_a_slot(prefs):
    row = dict(scope="notebook", notebook_id=NB, attribute="tone", value="x", signal="explicit", status="active", created_at=1.0)
    db.insert("preferences", {"id": "a", **row})
    with pytest.raises(sqlite3.IntegrityError):
        db.insert("preferences", {"id": "b", **row})


# --- scope ------------------------------------------------------------------------------------

def test_a_global_preference_is_stored_without_a_notebook_and_applies_everywhere(prefs):
    save("tone", "formal", scope="global")  # the tool always passes the chat's notebook, whatever the scope
    [row] = rows()
    assert row["scope"] == "global" and row["notebook_id"] is None
    assert active(NB)["tone"]["value"] == active(OTHER)["tone"]["value"] == "formal"


def test_a_notebook_preference_stays_in_its_notebook(prefs):
    save("tone", "casual")
    assert "tone" in active(NB) and "tone" not in active(OTHER)


def test_the_notebook_value_wins_over_the_global_one_for_the_same_attribute(prefs):
    save("tone", "formal", scope="global")
    save("tone", "casual", scope="notebook")
    assert active(NB)["tone"]["value"] == "casual"
    assert active(OTHER)["tone"]["value"] == "formal"
    assert len(rows(status="active")) == 2  # neither is superseded: the notebook one is an override, not a replacement


def test_correcting_in_one_scope_leaves_the_other_scope_alone(prefs):
    save("tone", "formal", scope="global")
    save("tone", "casual", scope="notebook")
    save("tone", "playful", scope="notebook", correction=True)
    assert rows(scope="global")[0]["status"] == "active" and rows(scope="global")[0]["value"] == "formal"
    assert active(NB)["tone"]["value"] == "playful"


def test_an_inferred_preference_applies_only_after_it_has_been_seen_twice(prefs):
    save("format", "bullets", signal="implicit")
    assert "format" not in active()
    save("format", "bullets", signal="implicit", session="s2")
    assert active()["format"]["value"] == "bullets"


def test_an_explicit_notebook_preference_beats_an_inferred_global_one_that_is_established(prefs):
    for session in ("s1", "s2", "s3"):
        save("tone", "casual", scope="global", signal="implicit", session=session)
    save("tone", "formal", scope="notebook")
    assert active()["tone"]["value"] == "formal"


# --- forgetting -------------------------------------------------------------------------------

def test_forgetting_a_preference_stops_it_applying_but_keeps_the_history(prefs):
    save()
    assert preferences.retract(NB, "answer_length", "notebook") is None
    assert "answer_length" not in active()
    assert rows()[0]["status"] == "retracted"


def test_forgetting_something_that_was_never_saved_says_so(prefs):
    assert isinstance(preferences.retract(NB, "tone", "notebook"), str)


def test_forgetting_only_touches_the_named_notebook_and_scope(prefs):
    save("tone", "formal", scope="global")
    save("tone", "casual", notebook=OTHER)
    save("tone", "playful")
    preferences.retract(NB, "tone", "notebook")
    assert active(OTHER)["tone"]["value"] == "casual"
    assert active(NB)["tone"]["value"] == "formal"  # the global one shows through again


def test_a_forgotten_slot_can_be_filled_again(prefs):
    save(value="short")
    preferences.retract(NB, "answer_length", "notebook")
    save(value="long")
    assert active()["answer_length"]["value"] == "long"


# --- the prompt note --------------------------------------------------------------------------

def test_there_is_no_note_when_nothing_is_saved(prefs):
    assert preferences.render_note(NB) == ""


def test_the_note_lists_what_applies_and_hides_internals(prefs):
    save("answer_length", "short")
    save("tone", "formal", scope="global")
    save("tone", "casual", notebook=OTHER)
    note = preferences.render_note(NB)
    assert note.startswith("# User preferences")
    assert "answer_length" in note and "short" in note and "formal" in note
    assert "casual" not in note  # another notebook's preference
    for hidden in (NB, "s1", "keep it short", "explicit", "notebook_id", "session_id"):
        assert hidden not in note


def test_the_note_leaves_out_replaced_and_forgotten_values(prefs):
    save("answer_length", "short")
    save("answer_length", "long")
    save("tone", "formal")
    preferences.retract(NB, "tone", "notebook")
    note = preferences.render_note(NB)
    assert "long" in note and "short" not in note and "formal" not in note


def test_inferred_preferences_are_marked_as_inferred_in_the_note(prefs):
    for session in ("s1", "s2"):
        save("format", "bullets", signal="implicit", session=session)
    save("tone", "formal")
    lines = {line for line in preferences.render_note(NB).splitlines() if "bullets" in line or "formal" in line}
    assert any("bullets" in line and "inferred" in line for line in lines)
    assert not any("formal" in line and "inferred" in line for line in lines)


# --- notebook deletion and the listing --------------------------------------------------------

def test_deleting_a_notebook_removes_its_preferences_but_not_the_global_ones(prefs):
    save("tone", "formal", scope="global")
    save("answer_length", "short")
    save("answer_length", "long", notebook=OTHER)
    preferences.delete_for_notebook(NB)
    assert {(r["attribute"], r["notebook_id"]) for r in rows()} == {("tone", None), ("answer_length", OTHER)}


def test_deleting_a_notebook_without_preferences_is_not_an_error(prefs):
    preferences.delete_for_notebook(NB)


def test_the_visible_list_has_the_notebooks_and_the_global_preferences_only(prefs):
    save("tone", "formal", scope="global")
    save("answer_length", "short")
    save("answer_length", "long", notebook=OTHER)
    save("format", "bullets")
    preferences.retract(NB, "format", "notebook")
    assert {(p["attribute"], p["value"]) for p in preferences.list_visible(NB)} == {("tone", "formal"), ("answer_length", "short")}


def test_removing_a_preference_by_id(prefs):
    save()
    [row] = rows()
    assert preferences.remove(row["id"]) is True
    assert preferences.remove(row["id"]) is False  # already gone
    assert preferences.remove("nope") is False
    assert preferences.list_visible(NB) == []


# --- the database -----------------------------------------------------------------------------

def test_execute_many_saves_everything_or_nothing(prefs):
    insert = "INSERT INTO notebooks (id, title, created_at, updated_at) VALUES (?, ?, 1, 1)"
    db.execute_many([(insert, ["a", "A"]), (insert, ["b", "B"])])
    assert {n["id"] for n in db.query("SELECT id FROM notebooks")} == {"a", "b"}

    with pytest.raises(sqlite3.IntegrityError):
        db.execute_many([(insert, ["c", "C"]), (insert, ["a", "again"])])  # the second one fails
    assert {n["id"] for n in db.query("SELECT id FROM notebooks")} == {"a", "b"}

    db.execute(insert, ["d", "D"])  # a later write must not carry the failed batch along
    assert {n["id"] for n in db.query("SELECT id FROM notebooks")} == {"a", "b", "d"}


def test_global_preferences_survive_the_startup_migration_that_adopts_orphans(tmp_path):
    path = tmp_path / "app.db"
    db.init(path)
    preferences.record(NB, "s1", "tone", "formal", "global", "explicit", "be formal", False)
    db.execute("INSERT INTO sessions (id, notebook_id, title, created_at, updated_at) VALUES ('x', NULL, 't', 1, 1)")
    db.init(path)  # an orphaned chat makes the migration assign notebook ids to rows that lack one
    assert rows(scope="global")[0]["notebook_id"] is None


def test_an_empty_preferences_table_from_before_the_redesign_is_replaced(tmp_path):
    path = tmp_path / "app.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE preferences (id TEXT PRIMARY KEY, notebook_id NULL, scope TEXT NOT NULL, attribute TEXT NOT NULL,
            value TEXT NOT NULL, source TEXT NOT NULL, explicit TEXT NOT NULL, created_at REAL NOT NULL,
            superseded_by TEXT NOT NULL, status TEXT NOT NULL);
    """)
    old.close()
    db.init(path)
    assert {"signal", "evidence", "session_id", "hits"} <= {c["name"] for c in db.query("PRAGMA table_info(preferences)")}
    save()  # and it works


# --- the API ----------------------------------------------------------------------------------

def test_the_api_lists_a_notebooks_preferences_with_the_global_ones(client):
    save("answer_length", "short", notebook=client.nb)
    save("tone", "formal", scope="global", notebook=client.nb)
    other = client.post("/api/notebooks", json={"title": "Other"}).json()["id"]
    save("tone", "casual", notebook=other)

    listed = client.get(nb_url(client, "preferences")).json()
    assert {(p["attribute"], p["value"], p["scope"]) for p in listed} == {("answer_length", "short", "notebook"), ("tone", "formal", "global")}
    assert {"id", "attribute", "value", "scope", "signal", "evidence"} <= listed[0].keys()


def test_listing_the_preferences_of_an_unknown_notebook_is_a_404(client):
    assert client.get("/api/notebooks/nope/preferences").status_code == 404


def test_a_preference_can_be_removed_through_the_api(client):
    save(notebook=client.nb)
    [pref] = client.get(nb_url(client, "preferences")).json()
    assert client.delete(f"/api/preferences/{pref['id']}").status_code == 204
    assert client.get(nb_url(client, "preferences")).json() == []
    assert client.delete(f"/api/preferences/{pref['id']}").status_code == 404


def test_deleting_a_notebook_through_the_api_removes_its_preferences_and_keeps_the_global_ones(client):
    save("answer_length", "short", notebook=client.nb)
    save("tone", "formal", scope="global", notebook=client.nb)
    other = client.post("/api/notebooks", json={"title": "Other"}).json()["id"]
    assert client.delete(f"/api/notebooks/{client.nb}").status_code == 204
    assert {(p["attribute"], p["scope"]) for p in client.get(f"/api/notebooks/{other}/preferences").json()} == {("tone", "global")}


# --- free-form ("other") preferences ----------------------------------------------------------

def test_a_fixed_attribute_is_stored_under_its_own_name_whatever_the_key(prefs):
    assert preferences.resolve_attribute("tone") == "tone"
    assert preferences.resolve_attribute("tone", "anything") == "tone"


def test_an_other_preference_is_stored_under_its_key(prefs):
    assert preferences.resolve_attribute("other", "emoji_use") == "other:emoji_use"


@pytest.mark.parametrize("key, expected", [
    ("No Emojis!", "other:no_emojis"),
    ("  page-numbers  ", "other:page_numbers"),
    ("__Cite__Style__", "other:cite_style"),
    ("Ünïcode ok", "other:n_code_ok"),
    ("x" * 100, "other:" + "x" * 40),
])
def test_keys_are_normalised_to_short_snake_case(prefs, key, expected):
    assert preferences.resolve_attribute("other", key) == expected


@pytest.mark.parametrize("key", ["", "   ", "!!!", "___", None])
def test_an_other_preference_without_a_usable_key_cannot_be_stored(prefs, key):
    assert preferences.resolve_attribute("other", key) is None


def test_a_key_that_names_a_fixed_attribute_uses_that_attribute(prefs):
    assert preferences.resolve_attribute("other", "Tone") == "tone"
    assert preferences.resolve_attribute("other", "answer length") == "answer_length"


def test_the_vocabulary_matches_what_the_tool_accepts(prefs):
    from typing import get_args

    from podcast_generation.agents.qa_chat.tools import QAChatAgentTools

    for tool in (QAChatAgentTools.update_user_preference, QAChatAgentTools.forget_user_preference):
        accepted = set(get_args(tool.args_schema.model_fields["attribute"].annotation))
        assert accepted == {*preferences.ATTRIBUTES, preferences.OTHER}


def test_different_keys_do_not_replace_each_other(prefs):
    save("other:emoji_use", "none")
    save("other:page_numbers", "always mention them")
    assert {(r["attribute"], r["status"]) for r in rows()} == {("other:emoji_use", "active"), ("other:page_numbers", "active")}
    assert {a: p["value"] for a, p in active().items()} == {"other:emoji_use": "none", "other:page_numbers": "always mention them"}


def test_the_same_key_is_replaced_by_a_newer_value(prefs):
    save("other:emoji_use", "none")
    save("other:emoji_use", "a few", correction=True)
    old, new = rows()
    assert (old["status"], old["superseded_by"], new["value"]) == ("superseded", new["id"], "a few")


def test_forgetting_one_key_leaves_the_other_keys(prefs):
    save("other:emoji_use", "none")
    save("other:page_numbers", "mention them")
    assert preferences.retract(NB, "other:emoji_use", "notebook") is None
    assert set(active()) == {"other:page_numbers"}


def test_the_note_names_a_free_form_preference_by_its_key(prefs):
    save("other:emoji_use", "none")
    note = preferences.render_note(NB)
    assert "- emoji_use: none" in note
    assert "other" not in note


def test_the_label_of_a_stored_attribute(prefs):
    assert preferences.label("other:emoji_use") == "emoji_use"
    assert preferences.label("tone") == "tone"
