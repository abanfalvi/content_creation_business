"""Deterministic unit tests for the Content Production Manager's own tools
and routing config — no LLM call involved, so these should be fast and
100% reproducible (see tests/cli/test_tui_send_message.py for the other
layer: mocking the agent itself to test orchestration behavior)."""
import json
from pathlib import Path

from src.agents.content_production.manager import ManagerTools, STEP_CONFIG


class _FakeRuntime:
    """Stands in for langchain's ToolRuntime so mark_posted's underlying
    function can be called directly, bypassing the real graph machinery."""

    def __init__(self, tool_call_id="test-call-id", **state):
        self.state = state
        self.tool_call_id = tool_call_id


def _write_calendar(tmp_path, influencer_name: str, entries: dict) -> Path:
    influencer_dir = tmp_path / "src" / "influencers" / influencer_name
    influencer_dir.mkdir(parents=True)
    calendar_path = influencer_dir / "CALENDAR.json"
    calendar_path.write_text(json.dumps(entries), encoding="utf-8")
    return calendar_path


def test_mark_posted_flips_only_the_matching_entry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calendar_path = _write_calendar(
        tmp_path,
        "test_influencer",
        {
            "2026-09-01": [
                {"id": "abc123", "theme": "morning routine", "status": "PLANNED"},
                {"id": "xyz789", "theme": "gym recap", "status": "PLANNED"},
            ]
        },
    )
    runtime = _FakeRuntime(influencer_name="test_influencer")

    result = ManagerTools.mark_posted.func(content_id="abc123", date="2026-09-01", runtime=runtime)

    assert result.update["messages"][0].content == "abc123 has been set to POSTED"
    updated = json.loads(calendar_path.read_text(encoding="utf-8"))
    assert updated["2026-09-01"][0]["status"] == "POSTED"
    assert updated["2026-09-01"][1]["status"] == "PLANNED"  # untouched


def test_mark_posted_unknown_id_leaves_calendar_unchanged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calendar_path = _write_calendar(
        tmp_path,
        "test_influencer",
        {"2026-09-01": [{"id": "abc123", "theme": "morning routine", "status": "PLANNED"}]},
    )
    runtime = _FakeRuntime(influencer_name="test_influencer")

    ManagerTools.mark_posted.func(content_id="does-not-exist", date="2026-09-01", runtime=runtime)

    updated = json.loads(calendar_path.read_text(encoding="utf-8"))
    assert updated["2026-09-01"][0]["status"] == "PLANNED"


def test_mark_posted_is_wired_into_the_content_creation_step():
    """Regression guard: the manager's system prompt tells it to call
    mark_posted right after the writer agent finishes, which only works if
    the tool is actually reachable in that step's tool set."""
    assert ManagerTools.mark_posted in STEP_CONFIG["content_creation"]["tools"]
