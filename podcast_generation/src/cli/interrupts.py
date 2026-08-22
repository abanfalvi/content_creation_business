import typer
from langgraph.types import Command
from rich.console import Console

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
    if "action_requests" in payload:
        for request in payload["action_requests"]:
            typer.echo(request.get("description", ""))
        return

    # Production's human_review_node: {"message", "audio_path", "rubric"}
    typer.echo(payload.get("message", ""))
    if payload.get("audio_path"):
        typer.echo(f"Audio: {payload['audio_path']}")
    if payload.get("rubric"):
        typer.echo(f"Rubric: {payload['rubric']}")
