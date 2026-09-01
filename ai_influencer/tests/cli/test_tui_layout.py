"""Regression tests for the chat transcript's layout.

Two things are being guarded here:
1. A past bug where the banner + info panel (auto-height, uncapped) could
   together exceed a normal terminal's height, pushing the message area
   entirely below the visible screen. Banner, info panel, and messages now
   share one scrollable container (#transcript) instead of being split into
   a separately-boxed, non-scrolling header region — so overflow anywhere in
   it is reachable by scrolling rather than rendered off-screen.
2. The message area (#log) should start at zero height and grow only as
   messages are actually mounted, instead of always claiming all leftover
   screen space as an empty block regardless of how much content it holds.
"""
import asyncio

from textual.containers import Vertical, VerticalScroll
from textual.widgets import Markdown

import src.cli.tui as tui_mod
from src.cli.tui import AgencyApp

# A handful of realistic terminal sizes, including the common ~24-row
# default that originally exposed the off-screen bug.
SIZES = [(80, 24), (100, 24), (100, 30), (120, 50)]


class _FakeState:
    def __init__(self, values):
        self.values = values


class _EmptyFakeAgent:
    """load_history() calls _get_orchestrator() on mount regardless of what
    a test cares about — without a mock it reaches for the real orchestrator,
    fails (no network/DB in tests), and mounts a "Could not reach the
    orchestrator" message into #log before the test body ever runs. That's
    harmless for tests only checking #transcript's bounds, but it silently
    breaks any test that assumes #log starts genuinely empty."""

    async def aget_state(self, config):
        return _FakeState({"messages": []})

    async def aupdate_state(self, config, values):
        pass


def _mock_orchestrator(monkeypatch):
    fake_agent = _EmptyFakeAgent()

    async def fake_get_orchestrator():
        return fake_agent

    monkeypatch.setattr(tui_mod, "_get_orchestrator", fake_get_orchestrator)


def test_transcript_is_always_within_the_visible_screen(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mock_orchestrator(monkeypatch)

    async def scenario(size):
        app = AgencyApp()
        async with app.run_test(size=size) as pilot:
            transcript = app.screen.query_one("#transcript", VerticalScroll)
            region = transcript.region
            assert region.height > 0, f"#transcript has zero height at size {size}"
            assert region.y + region.height <= size[1], f"#transcript extends past the bottom of a {size} terminal"

    for size in SIZES:
        asyncio.run(scenario(size))


def test_log_starts_empty_and_grows_as_messages_are_added(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mock_orchestrator(monkeypatch)

    async def scenario():
        app = AgencyApp()
        async with app.run_test(size=(100, 24)) as pilot:
            screen = app.screen
            log = screen.query_one("#log", Vertical)
            await pilot.pause()
            assert log.region.height == 0, "log should claim no space before any messages exist"

            await screen._mount_message("first message", "user")
            await pilot.pause()
            height_after_one = log.region.height
            assert height_after_one > 0

            await screen._mount_message("second message", "assistant")
            await pilot.pause()
            height_after_two = log.region.height
            assert height_after_two > height_after_one, "log should keep growing as more messages are mounted"

    asyncio.run(scenario())


def test_a_mounted_message_is_visible_on_a_typical_terminal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mock_orchestrator(monkeypatch)

    async def scenario():
        app = AgencyApp()
        async with app.run_test(size=(100, 24)) as pilot:
            screen = app.screen
            await screen._mount_message("hello there", "user")
            await pilot.pause()
            log = screen.query_one("#log", Vertical)
            widget = next(c for c in log.children if isinstance(c, Markdown))
            assert 0 <= widget.region.y
            assert widget.region.y + widget.region.height <= app.size.height

    asyncio.run(scenario())
