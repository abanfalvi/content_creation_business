"""Textual TUI for the agency: a fixed banner + departments/influencers panel
on top, a scrolling chat transcript with the orchestrator agent underneath,
and a status/input bar pinned to the bottom. Typing "/" opens a filterable
command menu above the input, the way slash-commands work in most agent
CLIs — more commands can be added to COMMANDS later without touching the
menu/filtering logic."""
import asyncio
import re
from pathlib import Path

from pyfiglet import figlet_format
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Markdown, OptionList, Static
from textual.widgets.option_list import Option

from src.cli.state import (
    DEFAULT_SESSION,
    all_sessions,
    get_default_influencer,
    new_auto_session,
    new_thread_id,
    resolve_thread_id,
)
from src.cli.tokens import TokenUsage, atrack_tokens

INFLUENCERS_DIR = Path("src/influencers")
# width=200 keeps this to a single figlet "line" (still ~5 text rows) instead
# of the ~12 rows two stacked lines cost — the header competes with #log for
# a typically-24-row terminal, so every row here is a row taken from the chat.
BANNER_TEXT = figlet_format("AI INFLUENCER AGENCY", font="small", width=200)

COMMANDS = [
    {"name": "/sessions", "description": "Browse, switch to, or start a new named session"},
    {"name": "/new", "description": "Start a fresh conversation in the current session"},
    {"name": "/influencers", "description": "Select the influencer to manage in this session"},
    {"name": "/quit", "description": "Quit the app"},
]

_orchestrator_agent = None
_orchestrator_lock = asyncio.Lock()


async def _get_orchestrator():
    global _orchestrator_agent
    async with _orchestrator_lock:
        if _orchestrator_agent is None:
            from src.orchestration.agent import get_orchestrator_agent
            _orchestrator_agent = await get_orchestrator_agent()
    return _orchestrator_agent


def list_influencers() -> list[dict]:
    influencers = []
    if not INFLUENCERS_DIR.exists():
        return influencers
    for folder in sorted(INFLUENCERS_DIR.iterdir()):
        if not folder.is_dir():
            continue
        blurb = ""
        character_path = folder / "CHARACTER.md"
        if character_path.exists():
            text = character_path.read_text(encoding="utf-8")
            match = re.search(r"Archetype.*?:\s*(.+)", text)
            if match:
                blurb = match.group(1).strip()
        influencers.append({"slug": folder.name, "name": folder.name.replace("_", " ").title(), "blurb": blurb})
    return influencers


def _content_to_text(content) -> str:
    """Some models return `content` as a string; others (reasoning models,
    some providers) return a list of typed content blocks instead — only the
    "text" blocks are the user-facing answer, so pull just those out rather
    than stringifying the whole block (which would render raw dict reprs,
    including internal reasoning, instead of the actual reply)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(part.get("text", ""))
            else:
                parts.append(str(part))
        return "\n".join(p for p in parts if p)
    return str(content) if content else ""


def _info_panel_text() -> str:
    lines = [
        "[bold]Departments[/bold]",
        "🎭 Persona & Identity      [green]online[/green]",
        "🎬 Content Production     [green]online[/green]",
        "💬 Engagement & Community [dim]not wired up yet[/dim]",
        "💸 Monetization           [dim]not wired up yet[/dim]",
        "",
        "[bold]Influencers[/bold]",
    ]
    influencers = list_influencers()
    if influencers:
        shown, extra = influencers[:6], influencers[6:]
        for inf in shown:
            entry = f"● {inf['name']}"
            if inf["blurb"]:
                entry += f"  [dim]{inf['blurb']}[/dim]"
            lines.append(entry)
        if extra:
            lines.append(f"[dim]… and {len(extra)} more (scroll up to see all)[/dim]")
    else:
        lines.append("[dim]None yet — ask the orchestrator to create one.[/dim]")
    lines.append("")
    count = len(influencers)
    lines.append(
        f"[dim]{count} influencer{'s' if count != 1 else ''} · 2 departments online · type / for sessions[/dim]"
    )
    return "\n".join(lines)


class SessionSwitcher(ModalScreen[tuple[str, str] | None]):
    """Lists known sessions and lets you jump to one, or type a new name to
    start (or resume) a differently named session."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current_session: str) -> None:
        super().__init__()
        self.current_session = current_session

    def compose(self) -> ComposeResult:
        with Vertical(id="switcher"):
            yield Static("[bold]Sessions[/bold]", id="switcher-title")
            with VerticalScroll(id="switcher-list"):
                sessions = all_sessions()
                if sessions:
                    for name in sorted(sessions):
                        label = f"{name} (current)" if name == self.current_session else name
                        yield Button(label, id=f"session-{name}", classes="session-item")
                else:
                    yield Static("[dim]No sessions yet.[/dim]")
            yield Input(placeholder="Type a name to switch/start a session...", id="new-session-input")

    def on_mount(self) -> None:
        self.query_one("#new-session-input", Input).focus()

    @on(Button.Pressed, ".session-item")
    def _pick(self, event: Button.Pressed) -> None:
        name = event.button.id.removeprefix("session-")
        self.dismiss((name, resolve_thread_id(name)))

    @on(Input.Submitted, "#new-session-input")
    def _create(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if not name:
            return
        self.dismiss((name, resolve_thread_id(name)))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ChatScreen(Screen):
    BINDINGS = [
        ("ctrl+n", "new_conversation", "New conversation"),
        ("ctrl+c", "interrupt", "Interrupt agent"),
        ("up", "menu_up", "Menu up"),
        ("down", "menu_down", "Menu down"),
        ("escape", "menu_close", "Close menu"),
    ]

    ROLE_LABELS = {"user": "You", "assistant": "Orchestrator", "system": "System"}
    SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    influencer_name: reactive[str | None] = reactive(None)
    session_tokens_in: reactive[int] = reactive(0)
    session_tokens_out: reactive[int] = reactive(0)
    busy: reactive[bool] = reactive(False)

    def __init__(self, thread_id: str, session: str = DEFAULT_SESSION) -> None:
        super().__init__()
        self.thread_id = thread_id
        self.session = session
        self._menu_mode = "commands"  # "commands" | "select_influencer"
        self._spinner_frame = 0
        self._spinner_timer = None

    def compose(self) -> ComposeResult:
        # Banner, info panel, and the message log all share one scrollable
        # flow rather than being split into separately-boxed regions: the
        # log starts at zero height and only grows as messages are added,
        # instead of instantly claiming all leftover screen space as an
        # empty block. Scrolling up from the latest message reaches the
        # banner/info panel the same way scrolling up reaches older messages.
        with VerticalScroll(id="transcript"):
            yield Static(BANNER_TEXT, id="banner")
            yield Static(
                "Persona creation & content production, coordinated by an agent orchestrator.",
                id="tagline",
            )
            yield Static(_info_panel_text(), id="info-panel")
            yield Vertical(id="log")
        with Vertical(id="bottom-bar"):
            yield Static(self._status_text(), id="status-bar")
            yield OptionList(id="command-menu")
            yield Input(placeholder='Try: "create a new fitness influencer", or / for commands', id="chat-input")

    def _status_text(self) -> str:
        if self.busy:
            frame = self.SPINNER_FRAMES[self._spinner_frame % len(self.SPINNER_FRAMES)]
            state = f"[yellow]{frame} thinking...[/yellow]"
        else:
            state = "[green]● ready[/green]"
        influencer = self.influencer_name or "none active"
        total = self.session_tokens_in + self.session_tokens_out
        return (
            f"{state}   ·   session: [bold]{self.session}[/bold]   ·   influencer: [bold]{influencer}[/bold]"
            f"   ·   tokens: {total}   ·   [dim]/ for commands · ctrl+c interrupt · ctrl+q quit[/dim]"
        )

    def _refresh_status(self) -> None:
        try:
            self.query_one("#status-bar", Static).update(self._status_text())
        except Exception:
            pass

    def watch_influencer_name(self, _old: str | None, _new: str | None) -> None:
        self._refresh_status()

    def watch_session_tokens_in(self, _old: int, _new: int) -> None:
        self._refresh_status()

    def watch_session_tokens_out(self, _old: int, _new: int) -> None:
        self._refresh_status()

    def watch_busy(self, _old: bool, new: bool) -> None:
        if new:
            self._spinner_frame = 0
            if self._spinner_timer is None:
                self._spinner_timer = self.set_interval(0.08, self._advance_spinner)
        elif self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        self._refresh_status()

    def _advance_spinner(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(self.SPINNER_FRAMES)
        self._refresh_status()

    def on_mount(self) -> None:
        self.query_one("#command-menu", OptionList).display = False
        self.query_one("#chat-input", Input).focus()
        self.load_history()

    def on_unmount(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    async def on_worker_state_changed(self, event) -> None:
        """Last-resort net: if a worker dies from something that escaped its
        own error handling, surface it instead of it vanishing into Textual's
        worker log while the UI just sits there looking idle."""
        from textual.worker import WorkerState

        if event.state is not WorkerState.ERROR:
            return
        self.busy = False
        await self._mount_message(f"Internal error in `{event.worker.name}`:\n\n{event.worker.error}", "system")
        try:
            input_widget = self.query_one("#chat-input", Input)
            input_widget.disabled = False
            input_widget.focus()
        except Exception:
            pass

    @work(exclusive=True)
    async def load_history(self) -> None:
        log = self.query_one("#log", Vertical)
        await log.remove_children()

        self.busy = True
        try:
            agent = await _get_orchestrator()
            config = {"configurable": {"thread_id": self.thread_id}}
            snapshot = await agent.aget_state(config)
        except Exception as exc:
            await self._mount_message(f"Could not reach the orchestrator: {exc}", "system")
            return
        finally:
            self.busy = False

        values = snapshot.values or {}
        self.influencer_name = values.get("influencer_name")
        if self.influencer_name is None:
            default_slug = get_default_influencer()
            if default_slug and any(inf["slug"] == default_slug for inf in list_influencers()):
                await agent.aupdate_state(config, {"influencer_name": default_slug})
                self.influencer_name = default_slug
        messages = values.get("messages", [])

        for message in messages:
            role = message.__class__.__name__
            if role == "AIMessage" and getattr(message, "tool_calls", None):
                for call in message.tool_calls:
                    await self._mount_tool_call(call)
            content = _content_to_text(getattr(message, "content", ""))
            if not content:
                continue
            if role == "HumanMessage":
                await self._mount_message(content, "user")
            elif role == "AIMessage":
                await self._mount_message(content, "assistant")

    def _scroll_log_to_end(self) -> None:
        self.query_one("#transcript", VerticalScroll).scroll_end(animate=False, immediate=True)

    def _schedule_scroll_to_end(self) -> None:
        # Markdown content can need an extra layout pass to settle after
        # mounting (its final height isn't always known after just one
        # refresh), so a single call_after_refresh can occasionally scroll
        # one line short of the true bottom — nesting it gives layout a
        # second pass before we commit to a final scroll position.
        self.call_after_refresh(lambda: self.call_after_refresh(self._scroll_log_to_end))

    async def _mount_message(self, content: str, role: str) -> None:
        label = self.ROLE_LABELS.get(role, role.title())
        widget = Markdown(f"**{label}:** {content}", classes=f"bubble {role}")
        log = self.query_one("#log", Vertical)
        await log.mount(widget)
        self._schedule_scroll_to_end()

    async def _mount_tool_call(self, call: dict) -> None:
        name = call.get("name", "tool")
        args = call.get("args") or {}
        args_text = ", ".join(f"{k}={v!r}" for k, v in args.items())
        widget = Static(f"[dim]🔧 {name}({args_text})[/dim]", classes="bubble tool-call")
        log = self.query_one("#log", Vertical)
        await log.mount(widget)
        self._schedule_scroll_to_end()

    async def _mount_graph_node_call(self, node_name: str) -> None:
        widget = Static(f"[dim]🔧 {node_name} is currently working...[/dim]", classes="bubble tool-call")
        log = self.query_one("#log", Vertical)
        await log.mount(widget)
        self._schedule_scroll_to_end()

    @on(Input.Changed, "#chat-input")
    def _on_input_changed(self, event: Input.Changed) -> None:
        if self._menu_mode != "commands":
            return
        self._update_command_menu(event.value)

    def _update_command_menu(self, value: str) -> None:
        menu = self.query_one("#command-menu", OptionList)
        matches = [c for c in COMMANDS if c["name"].startswith(value.lower())] if value.startswith("/") else []
        menu.clear_options()
        if not matches:
            menu.display = False
            return
        for command in matches:
            prompt = Text()
            prompt.append(f"{command['name']:<12}", style="bold")
            prompt.append(command["description"], style="dim")
            menu.add_option(Option(prompt, id=command["name"]))
        menu.highlighted = 0
        menu.display = True

    def action_menu_up(self) -> None:
        menu = self.query_one("#command-menu", OptionList)
        if menu.display:
            menu.action_cursor_up()

    def action_menu_down(self) -> None:
        menu = self.query_one("#command-menu", OptionList)
        if menu.display:
            menu.action_cursor_down()

    def action_menu_close(self) -> None:
        menu = self.query_one("#command-menu", OptionList)
        if menu.display:
            menu.display = False
        self._menu_mode = "commands"

    @on(OptionList.OptionSelected, "#command-menu")
    async def _on_command_selected(self, event: OptionList.OptionSelected) -> None:
        mode = self._menu_mode
        option_id = event.option.id
        input_widget = self.query_one("#chat-input", Input)
        event.option_list.display = False
        input_widget.value = ""

        if mode == "commands":
            await self._run_command(option_id)
        elif mode == "select_influencer":
            self._menu_mode = "commands"
            await self._set_active_influencer(option_id)

        input_widget.focus()

    async def _run_command(self, name: str | None) -> None:
        if name == "/sessions":
            self.app.push_screen(SessionSwitcher(self.session), self._on_switch_result)
        elif name == "/new":
            self.action_new_conversation()
        elif name == "/quit":
            self.app.exit()
        elif name == "/influencers":
            await self._open_influencer_menu()

    async def _open_influencer_menu(self) -> None:
        """Repopulate the same popup used for slash-commands with the
        influencer list instead, and switch its mode so the next selection
        is interpreted as an influencer pick rather than a command."""
        influencers = list_influencers()
        if not influencers:
            await self._mount_message("No influencers exist yet — ask the orchestrator to create one.", "system")
            return

        default_slug = get_default_influencer()
        menu = self.query_one("#command-menu", OptionList)
        menu.clear_options()
        for inf in influencers:
            marker = "★ " if inf["slug"] == default_slug else "  "
            prompt = Text()
            prompt.append(f"{marker}{inf['name']:<16}", style="bold")
            if inf["blurb"]:
                prompt.append(inf["blurb"], style="dim")
            menu.add_option(Option(prompt, id=inf["slug"]))
        menu.highlighted = 0
        menu.display = True
        self._menu_mode = "select_influencer"

    async def _set_active_influencer(self, slug: str | None) -> None:
        if not slug:
            return
        agent = await _get_orchestrator()
        config = {"configurable": {"thread_id": self.thread_id}}
        await agent.aupdate_state(config, {"influencer_name": slug})
        self.influencer_name = slug
        await self._mount_message(f"Now managing **{slug.replace('_', ' ').title()}** in this session.", "system")

    def _on_switch_result(self, result: tuple[str, str] | None) -> None:
        self.query_one("#chat-input", Input).focus()
        if result is None:
            return
        name, thread_id = result
        if name == self.session and thread_id == self.thread_id:
            return
        self.session = name
        self.thread_id = thread_id
        self.influencer_name = None
        self.session_tokens_in = 0
        self.session_tokens_out = 0
        self.load_history()

    @on(Input.Submitted, "#chat-input")
    async def _on_submit(self, event: Input.Submitted) -> None:
        menu = self.query_one("#command-menu", OptionList)
        if menu.display:
            menu.action_select()
            return

        text = event.value.strip()
        if not text:
            return
        input_widget = self.query_one("#chat-input", Input)
        input_widget.value = ""
        input_widget.disabled = True
        await self._mount_message(text, "user")
        self.send_message(text)

    @work(exclusive=True)
    async def send_message(self, text: str) -> None:
        config = {"configurable": {"thread_id": self.thread_id}}
        turn_usage = TokenUsage()
        outcome: dict = {}
        reply = None
        prompt = f"[Active influencer: {self.influencer_name}]\n\n{text}" if self.influencer_name else text
        self.busy = True
        try:
            try:
                agent = await _get_orchestrator()
                async with atrack_tokens(agent, self.thread_id) as usage:
                    seen = 0
                    async for mode, data in agent.astream({"messages": [("user", prompt)]}, config=config, stream_mode=["values", "custom"]):
                        if mode == "values":
                            outcome = data
                            messages = data.get("messages", [])
                            for message in messages[seen:]:
                                if getattr(message, "tool_calls", None):
                                    for call in message.tool_calls:
                                        await self._mount_tool_call(call)
                            seen = len(messages)
                        elif mode == "custom":
                            node_name = data.get("step")
                            node_name = node_name.removeprefix("call_") 
                            await self._mount_graph_node_call(node_name)
                if not outcome:
                    raise RuntimeError("The orchestrator finished without returning a response.")
                reply = _content_to_text(outcome["messages"][-1].content).strip()
                if not reply:
                    reply = "(no text reply — see the tool calls above for what ran)"
                self.influencer_name = outcome.get("influencer_name")
                turn_usage = usage
            except asyncio.CancelledError:
                reply = "_Interrupted (Ctrl+C) — the agent stopped before finishing this turn._"
                raise
            except Exception as exc:
                reply = f"Something went wrong talking to the orchestrator:\n\n{exc}"
        finally:
            # Guaranteed even on cancellation/unexpected errors so a failed
            # turn never vanishes silently, leaving the spinner/tokens/input
            # stuck with no visible explanation.
            self.busy = False
            self.session_tokens_in += turn_usage.input_tokens
            self.session_tokens_out += turn_usage.output_tokens
            try:
                await self._mount_message(reply or "(no response)", "assistant")
                input_widget = self.query_one("#chat-input", Input)
                input_widget.disabled = False
                input_widget.focus()
            except Exception:
                pass

    def action_new_conversation(self) -> None:
        self.thread_id = new_thread_id(self.session)
        self.influencer_name = None
        self.session_tokens_in = 0
        self.session_tokens_out = 0
        self.load_history()

    def action_interrupt(self) -> None:
        """Ctrl+C: stop the in-flight agent turn instead of quitting the app.
        Cancelling the worker unwinds through send_message's own
        CancelledError handling, which mounts a note and restores the input
        — nothing further to do here beyond finding the worker."""
        worker = next((w for w in self.workers if w.name == "send_message"), None)
        if worker is not None and not worker.is_finished:
            worker.cancel()


class AgencyApp(App):
    TITLE = "AI Influencer Agency"
    BINDINGS = [("ctrl+q", "quit", "Quit")]

    CSS = """
    #transcript {
        height: 1fr;
    }

    #banner {
        color: $accent;
        text-style: bold;
        width: 100%;
        content-align: center top;
        height: auto;
        padding-top: 1;
    }

    #tagline {
        text-align: center;
        color: $text-disabled;
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    #info-panel {
        border: round $primary;
        padding: 1 2;
        margin: 0 2 1 2;
        height: auto;
    }

    #log {
        padding: 0 2;
        height: auto;
    }

    .bubble {
        margin-bottom: 1;
        padding: 0 1;
        border-left: thick $primary;
    }

    .bubble.user {
        border-left: thick $success;
    }

    .bubble.assistant {
        border-left: thick $accent;
    }

    .bubble.system {
        border-left: thick $warning;
        color: $text-disabled;
    }

    .bubble.tool-call {
        border-left: thick $secondary;
        color: $text-disabled;
        padding: 0 1;
    }

    #bottom-bar {
        dock: bottom;
        height: auto;
    }

    #status-bar {
        background: $panel;
        padding: 0 2;
        width: 100%;
        height: auto;
    }

    #command-menu {
        border: round $accent;
        background: $surface;
        margin: 0 2;
        height: auto;
        max-height: 10;
    }

    #chat-input {
        margin: 0 2 1 2;
    }

    SessionSwitcher {
        align: center middle;
    }

    #switcher {
        width: 60;
        height: auto;
        max-height: 80%;
        border: heavy $accent;
        background: $surface;
        padding: 1 2;
    }

    #switcher-title {
        margin-bottom: 1;
    }

    #switcher-list {
        height: auto;
        max-height: 15;
        margin-bottom: 1;
    }

    .session-item {
        width: 100%;
        margin-bottom: 1;
    }
    """

    def on_mount(self) -> None:
        session, thread_id = new_auto_session()
        self.push_screen(ChatScreen(thread_id, session))


def run() -> None:
    AgencyApp().run()


if __name__ == "__main__":
    run()
