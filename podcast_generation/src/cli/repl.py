"""Interactive session launched by running `podcast` with no subcommand:
a banner, the current book wishlist, then a persistent `/command` prompt.

Dispatch reuses the exact same Click group the plain `podcast <command>`
invocations use (via typer.main.get_command), so the slash-menu below is
just a list of paths for the completer popup — not a second definition of
each command's arguments."""
import json
import shlex

import click
import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from pyfiglet import figlet_format
from rich.console import Console
from rich.panel import Panel

console = Console()

WORKFLOWS = [
    "/books search",
    "/books preprocess",
    "/content run",
    "/production run",
    "/distribution run",
    "/skills convert-traces",
    "/maintenance prune-checkpoints",
]

BOOK_LIST_PATH = "src/book_list.json"


def render_banner() -> None:
    banner = figlet_format("Level Up Lab", font="standard")
    console.print(f"[bold cyan]{banner}[/bold cyan]")


def render_wishlist() -> None:
    with open(BOOK_LIST_PATH, encoding="utf-8") as f:
        data = json.load(f)

    wishlist = data["list_of_books"]["wishlist"]
    console.print("[bold underline]Current wishlist[/bold underline]\n")
    for genre, books in wishlist.items():
        console.print(f"[bold yellow]{genre}[/bold yellow]")
        for book in books:
            console.print(Panel(book["abstract"], title=f"[bold]{book['title']}[/bold]", expand=False))
        console.print()


def _dispatch(line: str, click_group: click.Group) -> None:
    args = shlex.split(line[1:])
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
    console.print("Type [bold]/[/bold] to see available workflows, or 'exit' to quit.\n")

    session = PromptSession(completer=WordCompleter(WORKFLOWS, sentence=True, ignore_case=True), complete_while_typing=True)

    while True:
        try:
            line = session.prompt("level_up_lab> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if line in ("exit", "quit"):
            break
        if not line:
            continue
        if not line.startswith("/"):
            console.print("Commands start with /, e.g. /content run --book-title ...")
            continue

        _dispatch(line, click_group)
