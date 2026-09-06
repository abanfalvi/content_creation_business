import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

console = Console()

app = typer.Typer(help="CLI for the AI influencer agency. Run with no arguments to open the TUI.")


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from src.cli.tui import run as run_chat

        run_chat()


@app.command("chat")
def chat() -> None:
    """Open the interactive TUI (same as running with no arguments)."""
    from src.cli.tui import run as run_chat

    run_chat()


@app.command("sessions")
def sessions() -> None:
    """List known conversation sessions and the orchestrator thread each resumes."""
    from src.cli.state import all_sessions

    known = all_sessions()
    if not known:
        console.print("No sessions yet — run `chat` to start one.")
        raise typer.Exit()

    table = Table(title="Known sessions")
    table.add_column("Session")
    table.add_column("Thread ID")
    for name, thread_id in sorted(known.items()):
        table.add_row(name, thread_id)
    console.print(table)


@app.command("influencer")
def influencer() -> None:
    """Pick which influencer new sessions start with by default."""
    from src.cli.state import get_default_influencer, set_default_influencer
    from src.cli.tui import list_influencers

    influencers = list_influencers()
    if not influencers:
        console.print("No influencers exist yet — run `chat` and ask the orchestrator to create one.")
        raise typer.Exit()

    current = get_default_influencer()
    table = Table(title="Pick the default influencer")
    table.add_column("#", justify="right")
    table.add_column("Name")
    table.add_column("Blurb")
    for i, inf in enumerate(influencers, start=1):
        name = f"{inf['name']} [dim](current default)[/dim]" if inf["slug"] == current else inf["name"]
        table.add_row(str(i), name, inf["blurb"])
    console.print(table)

    choice = Prompt.ask("Influencer number", choices=[str(i) for i in range(1, len(influencers) + 1)])
    chosen = influencers[int(choice) - 1]
    set_default_influencer(chosen["slug"])
    console.print(f"[green]{chosen['name']}[/green] is now the default influencer for new sessions.")


if __name__ == "__main__":
    app()
