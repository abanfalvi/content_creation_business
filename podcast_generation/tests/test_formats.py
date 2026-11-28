"""Episode formats and the episode brief: the loader, the file a run writes, and where the agents read it."""
from types import SimpleNamespace

import pytest
from test_generation import (  # noqa: F401  (digests is an autouse fixture: it must be importable here too)
    SCRIPT, ScriptedGraph, add_ready_source, await_gate, digests, script_gate,
)

from podcast_generation.agents.content_specialists.director import tools as director_tools
from podcast_generation.agents.content_specialists.script_drafter_agent import revision_loop
from podcast_generation.agents.content_specialists.script_planner_agent import agent as planner
from podcast_generation.services import formats, generation
from podcast_generation.settings import DATA_DIR

BRIEF = DATA_DIR / "deep_work" / formats.BRIEF_FILENAME


@pytest.fixture(autouse=True)
def no_leftover_brief():
    """The data folder is shared by every test of the session: a brief must not leak from one to the next."""
    BRIEF.unlink(missing_ok=True)
    yield
    BRIEF.unlink(missing_ok=True)


def write_format(directory, name, *, label="Label", description="What it is.", default=False, body="Body.", **extra):
    meta = {"id": name, "label": label, "description": description, "default": default, **extra}
    head = "\n".join(f"{k}: {v}" for k, v in meta.items() if v is not None)
    (directory / f"{name}.md").write_text(f"---\n{head}\n---\n{body}\n", encoding="utf-8")


# --- the shipped files and the loader -------------------------------------------------------------

def test_the_shipped_formats_are_listed_in_order_with_one_default():
    listed = formats.list_formats()

    assert [f["id"] for f in listed] == ["deep_dive", "critical_overview", "debate", "brief", "custom"]
    assert [f["id"] for f in listed if f["default"]] == ["deep_dive"]
    assert [f["id"] for f in listed if f["needs_description"]] == ["custom"]  # the UI opens a box for these
    assert all(set(f) == {"id", "label", "description", "default", "needs_description"} for f in listed)  # nothing meant for the agents
    assert all(f["label"] and f["description"] for f in listed)


def test_the_default_format_adds_nothing_and_the_others_bring_their_own_plan_criteria():
    assert formats.default_format().id == "deep_dive" and formats.default_format().body == ""
    for fmt_id in ("critical_overview", "debate", "brief", "custom"):
        fmt = formats.get_format(fmt_id)
        assert fmt.body and fmt.plan_criteria and "\n" not in fmt.plan_criteria


@pytest.mark.parametrize("problem", ["no_label", "wrong_id", "two_defaults", "no_default"])
def test_a_broken_format_directory_is_rejected(tmp_path, problem):
    write_format(tmp_path, "one", default=problem != "no_default")
    if problem == "no_label":
        write_format(tmp_path, "two", label="")
    elif problem == "wrong_id":
        (tmp_path / "two.md").write_text("---\nid: other\nlabel: L\ndescription: D\n---\nBody\n", encoding="utf-8")
    elif problem == "two_defaults":
        write_format(tmp_path, "two", default=True)
    else:
        write_format(tmp_path, "two")

    with pytest.raises(formats.FormatError):
        formats.load_formats(tmp_path)


def test_requests_are_checked():
    assert formats.resolve(None, None)[0].id == "deep_dive"  # nothing named: the default
    fmt, text, described = formats.resolve("debate", "  focus on managers \n", "ignored: debate has its own structure")
    assert (fmt.id, text, described) == ("debate", "focus on managers", "")
    with pytest.raises(formats.FormatError, match="Unknown format 'poem'"):
        formats.resolve("poem", "")
    with pytest.raises(formats.FormatError, match="under 1500"):
        formats.resolve("brief", "x" * (formats.MAX_INSTRUCTIONS + 1))
    formats.resolve("brief", "x" * formats.MAX_INSTRUCTIONS)  # exactly the limit is fine


def test_the_custom_format_needs_a_description_of_the_episode():
    for missing in (None, "", "   "):
        with pytest.raises(formats.FormatError, match="needs a description"):
            formats.resolve("custom", "", missing)
    with pytest.raises(formats.FormatError, match="description under 1500"):
        formats.resolve("custom", "", "x" * (formats.MAX_INSTRUCTIONS + 1))

    fmt, _, described = formats.resolve("custom", "", "  Three segments, interview style  ")
    brief = formats.compose_brief(fmt, "Keep it light", described)
    assert described == "Three segments, interview style"
    assert brief.index("## Episode format: Custom") < brief.index("### The user's description of the episode\nThree segments, interview style")
    assert brief.index("### The user's description") < brief.index("## Custom instructions from the user\nKeep it light")


# --- the brief ------------------------------------------------------------------------------------

def test_the_brief_is_the_format_plus_the_instructions_and_nothing_for_a_plain_default_run():
    default, debate = formats.get_format("deep_dive"), formats.get_format("debate")

    assert formats.compose_brief(default) is None and formats.compose_brief(default, "   ") is None

    only_instructions = formats.compose_brief(default, "For beginners")
    assert only_instructions.startswith("<!-- format: deep_dive -->\n\n# Episode brief")
    assert "## Custom instructions from the user\nFor beginners" in only_instructions
    assert "Episode format" not in only_instructions and "the format below" not in only_instructions

    only_format = formats.compose_brief(debate)
    assert "## Episode format: Debate" in only_format and debate.body in only_format
    assert "Custom instructions" not in only_format

    both = formats.compose_brief(debate, "Focus on what this means for managers")
    assert both.index("## Episode format: Debate") < both.index("## Custom instructions from the user")
    assert both.rstrip().endswith("Focus on what this means for managers")
    assert "never allow a fact the sources do not contain" in both  # the instructions are a steer, not source material


def test_a_run_writes_its_brief_and_a_new_run_moves_it_aside():
    formats.write_brief("deep_work", formats.get_format("debate"), "For managers")
    assert "## Episode format: Debate" in formats.read_brief("deep_work")

    generation._archive_previous_run("deep_work")  # what starting the next run does first

    assert formats.read_brief("deep_work") == ""
    assert any(p.read_text(encoding="utf-8").startswith("<!-- format: debate -->")
               for p in (DATA_DIR / "deep_work" / "archive").glob(f"*/{formats.BRIEF_FILENAME}"))


def test_the_planners_judge_uses_the_runs_format_criteria():
    assert formats.plan_criteria("deep_work") == ""  # no brief
    assert planner._ready_question("deep_work")[0] == planner.READY_CRITERIA

    formats.write_brief("deep_work", formats.get_format("deep_dive"), "For beginners")
    assert formats.plan_criteria("deep_work") == ""  # the standard format keeps the standard criteria

    formats.write_brief("deep_work", formats.get_format("debate"), "")
    criteria, question = planner._ready_question("deep_work")
    assert criteria == formats.get_format("debate").plan_criteria != planner.READY_CRITERIA
    assert question["criteria"] == {"true": criteria, "false": planner.READY_NOT_CRITERIA}
    assert planner.ARTIFACT_READY_QUESTION["criteria"]["true"] == planner.READY_CRITERIA  # the shared question is untouched


def test_evaluators_are_shown_the_brief_only_when_the_run_has_one():
    book_file = DATA_DIR / "deep_work" / "book_content.md"
    ctx = {"script": SCRIPT, "plan": None, "expert": None, "host": None, "book_file": book_file, "episode_format": ""}

    plain = revision_loop._compose_message("Deep Work", ctx, ("plan",))
    assert "<episode_format>" not in plain and "<draft_script>" in plain

    formats.write_brief("deep_work", formats.get_format("brief"), "Keep it light")
    ctx["episode_format"] = revision_loop._load_context("Deep Work")["episode_format"]
    briefed = revision_loop._compose_message("Deep Work", ctx, ("plan",))
    assert "<episode_format>\n<!-- format: brief -->" in briefed and "Keep it light" in briefed


# --- the agents are given the brief by code, not by the director model ---------------------------

class FakeAgent:
    def __init__(self):
        self.inputs = []

    def invoke(self, value, config=None):
        self.inputs.append(value["messages"][0]["content"])
        return {"messages": [SimpleNamespace(content="done")]}


def test_the_director_hands_the_brief_to_the_expert_builder_the_planner_and_the_drafter(monkeypatch):
    expert, planner_agent, drafter = FakeAgent(), FakeAgent(), FakeAgent()
    monkeypatch.setattr(director_tools, "expert_builder_agent", expert)
    monkeypatch.setattr(director_tools, "script_planner_agent", planner_agent)
    monkeypatch.setattr(director_tools, "script_drafter_agent", drafter)
    folder = DATA_DIR / "deep_work"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "expert_persona.md").write_text("Dr. Sam", encoding="utf-8")
    (folder / "script_plan.md").unlink(missing_ok=True)
    runtime = SimpleNamespace(state={"book_title": "Deep Work"}, store=None, tool_call_id="call-1",
                              execution_info=SimpleNamespace(thread_id="job-1"))
    build, draft = director_tools.DirectorTools.call_expert_builder_agent.func, director_tools.DirectorTools.call_script_drafter_agent.func

    # a plain run: the queries are exactly what the director wrote
    build("Build the expert", runtime)
    draft("Draft it", runtime)
    assert expert.inputs == ["Build the expert"] and drafter.inputs == ["Draft it"]
    assert planner_agent.inputs == ["Plan the script for the next book: Deep Work"]

    # a run with a brief: all three get it appended, including a re-plan after the user rejected the script
    formats.write_brief("deep_work", formats.get_format("debate"), "For managers")
    expert.inputs.clear(), planner_agent.inputs.clear(), drafter.inputs.clear()
    build("Build the expert", runtime)
    draft("Revise the intro", runtime, replan=True)
    for sent in (expert.inputs[0], planner_agent.inputs[0], drafter.inputs[0]):
        assert "## Episode format: Debate" in sent and sent.rstrip().endswith("For managers")
    assert expert.inputs[0].startswith("Build the expert") and drafter.inputs[0].startswith("Revise the intro")
    assert "Revise the intro" in planner_agent.inputs[0]  # the re-plan keeps the reason it was asked for


# --- the API ---------------------------------------------------------------------------------------

def test_the_formats_endpoint_lists_what_the_ui_needs(client):
    listed = client.get("/api/formats")

    assert listed.status_code == 200
    assert listed.json() == formats.list_formats()
    assert "Episode format" not in listed.text and "plan_criteria" not in listed.text


def test_generate_checks_the_format_and_the_instructions_before_doing_anything(client, monkeypatch):
    add_ready_source(client, monkeypatch)

    unknown = client.post("/api/generate", json={"source_slug": "deep_work", "format": "poem"})
    assert unknown.status_code == 422 and "Unknown format" in unknown.json()["detail"]
    long = client.post("/api/generate", json={"source_slug": "deep_work", "instructions": "x" * 2000})
    assert long.status_code == 422
    assert client.get(f"/api/notebooks/{client.nb}/jobs").json() == [] and not BRIEF.exists()


def test_a_run_in_a_format_gets_its_brief_and_a_plain_run_does_not(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    content = ScriptedGraph(script_gate(), script_gate())
    monkeypatch.setattr(generation, "get_content_director", lambda: content)

    started = client.post("/api/generate", json={"source_slug": "deep_work", "format": "debate", "instructions": " For managers "})

    assert started.status_code == 202
    assert started.json()["result"]["format"] == "debate" and started.json()["result"]["instructions"] == "For managers"
    brief = BRIEF.read_text(encoding="utf-8")  # written before the run starts, so the first agent already has it
    assert "## Episode format: Debate" in brief and brief.rstrip().endswith("For managers")
    await_gate(client, started.json()["id"], "script")
    assert content.inputs[0]["book_title"] == "Deep Work"  # the brief travels by file, not through the graph state


def test_a_custom_run_needs_its_description_and_carries_it_into_the_brief(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    content = ScriptedGraph(script_gate())
    monkeypatch.setattr(generation, "get_content_director", lambda: content)

    refused = client.post("/api/generate", json={"source_slug": "deep_work", "format": "custom", "instructions": "Light"})
    assert refused.status_code == 422 and "needs a description" in refused.json()["detail"] and not BRIEF.exists()

    started = client.post("/api/generate", json={
        "source_slug": "deep_work", "format": "custom", "format_description": "Three segments, interview style"})

    assert started.status_code == 202 and started.json()["result"]["format_description"] == "Three segments, interview style"
    brief = BRIEF.read_text(encoding="utf-8")
    assert "## Episode format: Custom" in brief and "Three segments, interview style" in brief
    await_gate(client, started.json()["id"], "script")
    assert formats.plan_criteria("deep_work") == formats.get_format("custom").plan_criteria  # the planner's judge follows it


def test_a_plain_run_is_the_default_format_without_a_brief(client, monkeypatch):
    add_ready_source(client, monkeypatch)
    monkeypatch.setattr(generation, "get_content_director", lambda: ScriptedGraph(script_gate()))

    started = client.post("/api/generate", json={"source_slug": "deep_work"}).json()

    assert started["result"]["format"] == "deep_dive" and started["result"]["instructions"] == ""
    assert not BRIEF.exists()
    await_gate(client, started["id"], "script")
