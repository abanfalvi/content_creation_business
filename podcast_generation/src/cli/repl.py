"""Interactive session launched by running `podcast` with no subcommand:
a banner, the current book wishlist, then a persistent `/command` prompt.

Dispatch reuses the exact same Click group the plain `podcast <command>`
invocations use (via typer.main.get_command), so the slash-menu below is
just a list of paths for the completer popup — not a second definition of
each command's arguments. Guided prompting (COMMAND_SPECS / guided_args)
is REPL-only convenience layered on top for a bare command selection;
typing any arguments yourself still dispatches directly, unchanged."""
import json
import shlex

import click
import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from pyfiglet import figlet_format
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from src.cli.state import all_threads

console = Console()

WORKFLOWS = [
    "/books search",
    "/books preprocess",
    "/content run",
    "/production run",
    "/distribution run",
    "/skills convert-traces",
    "/maintenance prune-checkpoints",
    "/status",
]

BOOK_LIST_PATH = "src/book_list.json"

CONTENT_STEPS = [
    "call_book_selection_agent", "call_expert_builder_agent", "call_script_drafter_agent",
    "edit_prompts_skills", "review_expert_profile", "human_review",
    "get_lessons_learned", "full_flexibility",
]
DISTRIBUTION_STEPS = [
    "call_sm_writer_agent", "call_publisher_agent", "edit_prompts", "review_post", "get_lessons_learned",
]

# One entry per dispatchable command: each field is either positional
# (kind "text"/"choice") or an option (name starts with "--"). "book_picker"
# fields prompt via pick_book() instead of free text, guaranteeing an
# exact-match title (see the thread-continuity discussion this sidesteps).
COMMAND_SPECS: dict[str, list[dict]] = {
    "/books search": [
        {"name": "query", "positional": True, "kind": "text"},
        {"name": "--thread-id", "kind": "text_optional"},
    ],
    "/books preprocess": [
        {"name": "--book-genre", "kind": "text"},
        {"name": "--book-name", "kind": "text"},
        {"name": "--end-page", "kind": "text"},
    ],
    "/content run": [
        {"name": "query", "positional": True, "kind": "text"},
        {"name": "--book-title", "kind": "book_picker"},
        {"name": "--step", "kind": "choice", "choices": CONTENT_STEPS, "default": "call_expert_builder_agent"},
        {"name": "--thread-id", "kind": "text_optional"},
    ],
    "/production run": [
        {"name": "--book-title", "kind": "book_picker"},
        {"name": "--expert-name", "kind": "text"},
        {"name": "--script", "kind": "text_optional"},
        {"name": "--feedback", "kind": "text_optional"},
        {"name": "--thread-id", "kind": "text_optional"},
    ],
    "/distribution run": [
        {"name": "--book-title", "kind": "book_picker"},
        {"name": "--query", "kind": "text_optional", "default": "Prepare the podcast episode for publishing"},
        {"name": "--script-path", "kind": "text_optional"},
        {"name": "--step", "kind": "choice", "choices": DISTRIBUTION_STEPS, "default": "call_sm_writer_agent"},
        {"name": "--thread-id", "kind": "text_optional"},
    ],
    "/skills convert-traces": [
        {"name": "namespace", "positional": True, "kind": "choice",
         "choices": ["content_traces", "production_traces", "distribution_traces"]},
        {"name": "--book-title", "kind": "book_picker"},
    ],
    "/maintenance prune-checkpoints": [
        {"name": "--db", "kind": "choice", "choices": ["content", "production", "distribution", "all"], "default": "all"},
    ],
}


def render_banner() -> None:
    banner = figlet_format("Level Up Lab", font="standard")
    console.print(f"[bold cyan]{banner}[/bold cyan]")


def load_books() -> list[dict]:
    with open(BOOK_LIST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    books = []
    for genre, entries in data["list_of_books"]["wishlist"].items():
        for entry in entries:
            books.append({"genre": genre, **entry})
    return books


def render_wishlist() -> None:
    books = load_books()
    console.print("[bold underline]Current wishlist[/bold underline]\n")
    genre = None
    for book in books:
        if book["genre"] != genre:
            genre = book["genre"]
            console.print(f"[bold yellow]{genre}[/bold yellow]")
        console.print(Panel(book["abstract"], title=f"[bold]{book['title']}[/bold]", expand=False))
    console.print()


def pick_book() -> str:
    books = load_books()
    table = Table(title="Pick a book")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Genre")
    for i, book in enumerate(books, start=1):
        table.add_row(str(i), book["title"], book["genre"])
    console.print(table)

    choice = Prompt.ask("Book number", choices=[str(i) for i in range(1, len(books) + 1)])
    return books[int(choice) - 1]["title"]


def guided_args(command: str) -> tuple[list[str], str | None]:
    """Prompt for every field COMMAND_SPECS declares for `command`. Returns
    the flat arg list ready to dispatch, plus the picked book title (if any)
    so the caller can update the REPL's session context."""
    args: list[str] = []
    picked_book: str | None = None

    for field in COMMAND_SPECS.get(command, []):
        label = field["name"].lstrip("-").replace("-", " ")
        kind = field["kind"]

        if kind == "book_picker":
            value = pick_book()
            picked_book = value
        elif kind == "choice":
            value = Prompt.ask(label, choices=field["choices"], default=field.get("default"))
        elif kind == "text_optional":
            value = Prompt.ask(f"{label} (optional)", default=field.get("default", ""))
            if not value:
                continue
        else:
            value = Prompt.ask(label)

        if field.get("positional"):
            args.append(value)
        else:
            args.extend([field["name"], value])

    return args, picked_book


def _extract_book_title(line: str) -> str | None:
    """Light scan for --book-title in a directly-typed (non-guided) line,
    just to keep the REPL's session-context display in sync — not a real
    parse, Click still does the actual argument handling in _dispatch."""
    try:
        parts = shlex.split(line[1:])
    except ValueError:
        return None
    for i, part in enumerate(parts):
        if part == "--book-title" and i + 1 < len(parts):
            return parts[i + 1]
    return None


def _show_status(current_book: str | None) -> None:
    console.print(f"Current book: [bold]{current_book or '(none selected yet)'}[/bold]\n")
    threads = all_threads()
    if not threads:
        console.print("No threads recorded yet.")
        return
    table = Table(title="Known threads (.podcast_cli/state.json)")
    table.add_column("Book / key")
    table.add_column("Tier")
    table.add_column("Thread ID")
    for slot, thread_id in sorted(threads.items()):
        key, _, tier = slot.rpartition("::")
        table.add_row(key, tier, thread_id)
    console.print(table)


def _dispatch(args: list[str], click_group: click.Group) -> None:
    if not args:
        return
    try:
        click_group.main(args=args, prog_name="podcast", standalone_mode=False)
    except click.exceptions.UsageError as exc:
        exc.show()
    except click.exceptions.Exit:
        pass
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")


def run_repl() -> None:
    from src.cli.main import app

    click_group = typer.main.get_command(app)

    render_banner()
    # render_wishlist()
    console.print("Type [bold]/[/bold] to see available workflows, [bold]/status[/bold] for session info, or 'exit' to quit.\n")

    session = PromptSession(completer=WordCompleter(WORKFLOWS, sentence=True, ignore_case=True), complete_while_typing=True)
    current_book: str | None = None

    while True:
        prompt_label = f"level_up_lab ({current_book})> " if current_book else "level_up_lab> "
        try:
            line = session.prompt(prompt_label).strip()
        except (EOFError, KeyboardInterrupt):
            break

        if line in ("exit", "quit"):
            break
        if not line:
            continue
        if line == "/status":
            _show_status(current_book)
            continue
        if not line.startswith("/"):
            console.print("Commands start with /, e.g. /content run --book-title ...")
            continue

        if line in COMMAND_SPECS:
            try:
                args, picked_book = guided_args(line)
            except (EOFError, KeyboardInterrupt):
                console.print("\nCancelled.")
                continue
            if picked_book:
                current_book = picked_book
            _dispatch(shlex.split(line[1:]) + args, click_group)
            continue

        book_title = _extract_book_title(line)
        if book_title:
            current_book = book_title
        _dispatch(shlex.split(line[1:]), click_group)
