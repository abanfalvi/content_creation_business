"""Mocked-agent tests for the chat worker in src/cli/tui.py.

Rather than exercising the real orchestrator (which needs live model/DB
access and is non-deterministic), these swap in a scripted fake agent so the
test asserts on the TUI's own behavior: does a reply get mounted, do token
counts update, does the input re-enable, does a cancelled turn still tell
the user something happened instead of vanishing silently."""
import asyncio

from textual.containers import Vertical
from textual.widgets import Input, Markdown

import src.cli.tui as tui_mod
from src.cli.tui import AgencyApp


class _AIMessage:
    def __init__(self, content, usage_metadata=None):
        self.content = content
        self.usage_metadata = usage_metadata
        self.tool_calls = []


class _HumanMessage:
    def __init__(self, content):
        self.content = content
        self.tool_calls = []


class _FakeState:
    def __init__(self, values):
        self.values = values


class _FakeAgentSuccess:
    """A normal turn: echoes the human message back, then replies once."""

    def __init__(self):
        self._messages = []

    async def aget_state(self, config):
        return _FakeState({"messages": list(self._messages)})

    async def aupdate_state(self, config, values):
        pass

    async def astream(self, input_, config, stream_mode="values"):
        self._messages.append(_HumanMessage(input_["messages"][0][1]))
        yield {"messages": list(self._messages)}
        self._messages.append(
            _AIMessage(
                "Hello from the orchestrator!",
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        )
        yield {"messages": list(self._messages)}


class _FakeAgentHangs:
    """A turn that never resolves, so the test can cancel its worker mid-
    flight — reproducing the exact failure mode of a past bug: cancelling
    the in-flight `send_message` worker raised asyncio.CancelledError, which
    (being a BaseException, not an Exception) slipped past the old
    `except Exception` handling and left the chat, spinner, and token count
    exactly as if nothing had happened."""

    def __init__(self):
        self._messages = []

    async def aget_state(self, config):
        return _FakeState({"messages": list(self._messages)})

    async def aupdate_state(self, config, values):
        pass

    async def astream(self, input_, config, stream_mode="values"):
        self._messages.append(_HumanMessage(input_["messages"][0][1]))
        yield {"messages": list(self._messages)}
        await asyncio.sleep(30)
        yield {"messages": list(self._messages)}  # pragma: no cover - never reached


def _mounted_markdown_text(log: Vertical) -> list[str]:
    return [getattr(child, "_markdown", "") or str(child.render()) for child in log.children if isinstance(child, Markdown)]


async def _wait_until_idle(pilot, screen, attempts=50, step=0.05) -> None:
    for _ in range(attempts):
        await pilot.pause(step)
        if not screen.busy:
            return
    raise AssertionError("screen stayed busy — the worker never finished")


def test_send_message_shows_reply_and_updates_tokens(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_agent = _FakeAgentSuccess()

    async def fake_get_orchestrator():
        return fake_agent

    monkeypatch.setattr(tui_mod, "_get_orchestrator", fake_get_orchestrator)

    async def scenario():
        app = AgencyApp()
        async with app.run_test(size=(120, 50)) as pilot:
            screen = app.screen
            input_widget = screen.query_one("#chat-input", Input)
            input_widget.value = "hi there"
            await pilot.pause()
            await pilot.press("enter")
            await _wait_until_idle(pilot, screen)

            log = screen.query_one("#log", Vertical)
            texts = _mounted_markdown_text(log)
            assert any("Hello from the orchestrator" in t for t in texts)
            assert screen.session_tokens_in == 10
            assert screen.session_tokens_out == 5
            assert not input_widget.disabled

    asyncio.run(scenario())


def test_send_message_cancellation_is_not_silent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_agent = _FakeAgentHangs()

    async def fake_get_orchestrator():
        return fake_agent

    monkeypatch.setattr(tui_mod, "_get_orchestrator", fake_get_orchestrator)

    async def scenario():
        app = AgencyApp()
        async with app.run_test(size=(120, 50)) as pilot:
            screen = app.screen
            input_widget = screen.query_one("#chat-input", Input)
            input_widget.value = "this will hang"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert screen.busy, "expected busy=True while the fake call is hanging"

            send_worker = next(w for w in screen.workers if w.name == "send_message")
            send_worker.cancel()

            await _wait_until_idle(pilot, screen)

            log = screen.query_one("#log", Vertical)
            texts = _mounted_markdown_text(log)
            assert any("Interrupted" in t for t in texts)
            assert not input_widget.disabled

    asyncio.run(scenario())


def test_ctrl_c_interrupts_agent_without_quitting_app(tmp_path, monkeypatch):
    """Ctrl+C used to quit the whole app (a destructive default for a key
    people reflexively hit to stop a running command) — it should now
    interrupt just the in-flight turn, leaving the app open."""
    monkeypatch.chdir(tmp_path)
    fake_agent = _FakeAgentHangs()

    async def fake_get_orchestrator():
        return fake_agent

    monkeypatch.setattr(tui_mod, "_get_orchestrator", fake_get_orchestrator)

    async def scenario():
        app = AgencyApp()
        async with app.run_test(size=(120, 50)) as pilot:
            screen = app.screen
            input_widget = screen.query_one("#chat-input", Input)
            input_widget.value = "this will hang"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert screen.busy

            await pilot.press("ctrl+c")
            await _wait_until_idle(pilot, screen)

            assert app.is_running, "ctrl+c should interrupt the turn, not quit the app"
            log = screen.query_one("#log", Vertical)
            texts = _mounted_markdown_text(log)
            assert any("Interrupted" in t for t in texts)
            assert not input_widget.disabled

    asyncio.run(scenario())


def test_ctrl_q_quits_the_app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def scenario():
        app = AgencyApp()
        async with app.run_test(size=(120, 50)) as pilot:
            assert app.is_running
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert not app.is_running

    asyncio.run(scenario())
