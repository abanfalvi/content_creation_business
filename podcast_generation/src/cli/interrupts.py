import typer
from langgraph.types import Command
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

console = Console()


def resolve_interrupts(graph, outcome: dict, config: dict) -> dict:
    while "__interrupt__" in outcome:
        payload = outcome["__interrupt__"][0].value
        _display(payload)

        if typer.confirm("Approve?"):
            decision = {"approved": True}
        else:
            decision = {"approved": False, "feedback": typer.prompt("What needs to change?")}

        with console.status("[bold cyan]Running...[/bold cyan]", spinner="dots"):
            outcome = graph.invoke(Command(resume=decision), config=config)
    return outcome


def _display(payload: dict) -> None:
    # Content director's human_review: {"action_requests": [{"description": "..."}]}
    # description packs instructions + script together, joined on "\n\n---\n"
    # (see director_tools.py's human_review tool) — split so the script
    # renders as markdown instead of a raw text blob.
    if "action_requests" in payload:
        for request in payload["action_requests"]:
            description = request.get("description", "")
            instructions, sep, script = description.partition("\n\n---\n")
            console.print(instructions)
            if sep:
                console.print(Markdown(script))
        return

    # Production's human_review_node: {"message", "audio_path", "rubric"}
    console.print(payload.get("message", ""))
    if payload.get("audio_path"):
        console.print(f"Audio: {payload['audio_path']}")
    if payload.get("rubric"):
        _render_rubric(payload["rubric"])


def _render_rubric(rubric: dict) -> None:
    table = Table(title="Audio review rubric")
    table.add_column("Dimension")
    table.add_column("Score", justify="right")

    score_fields = ["loudness_consistency", "noise_clarity", "silence_pacing", "transitions", "technical_compliance"]
    for field in score_fields:
        if field in rubric:
            table.add_row(field.replace("_", " "), str(rubric[field]))
    console.print(table)

    if rubric.get("evidence"):
        console.print(f"[bold]Evidence:[/bold] {rubric['evidence']}")
