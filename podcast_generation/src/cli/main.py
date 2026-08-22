import asyncio
from typing import Optional

import typer
from rich.console import Console

from src.cli.interrupts import resolve_interrupts
from src.cli.state import resolve_thread_id
from src.cli.tokens import atrack_tokens, render_usage, track_tokens

console = Console()

app = typer.Typer(help="CLI for the podcast production pipeline.")
books_app = typer.Typer(help="Book discovery and ingestion.")
content_app = typer.Typer(help="Content specialists: book selection, expert profile, script drafting.")
production_app = typer.Typer(help="Production specialists: TTS generation, audio engineering.")
distribution_app = typer.Typer(help="Distribution specialists: social posts, publishing.")
skills_app = typer.Typer(help="Convert saved traces into reusable skills.")
maintenance_app = typer.Typer(help="Checkpoint housekeeping.")

app.add_typer(books_app, name="books")
app.add_typer(content_app, name="content")
app.add_typer(production_app, name="production")
app.add_typer(distribution_app, name="distribution")
app.add_typer(skills_app, name="skills")
app.add_typer(maintenance_app, name="maintenance")


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        from src.cli.repl import run_repl

        run_repl()


@books_app.command("search")
def books_search(
    query: str,
    thread_id: Optional[str] = typer.Option(None, help="Resume a specific book-selection thread."),
):
    """Find new candidate books, or expand/refine the existing shortlist."""
    from src.agents.content_specialists.book_selection_agent import book_selection_agent

    tid = resolve_thread_id(key="_global", tier="book_selection", thread_id=thread_id)
    with track_tokens(book_selection_agent, tid) as usage:
        with console.status("[bold cyan]Searching...[/bold cyan]", spinner="dots"):
            outcome = book_selection_agent.invoke(
                {"messages": [("user", query)]},
                config={"configurable": {"thread_id": tid}},
            )
    typer.echo(outcome["messages"][-1].content)
    render_usage(usage)


@books_app.command("preprocess")
def books_preprocess(
    book_genre: str = typer.Option(..., help="Genre key as listed in src/book_list.json."),
    book_name: str = typer.Option(..., help="Book title as listed in src/book_list.json."),
    end_page: int = typer.Option(..., help="Last page to parse from the source PDF."),
):
    """Parse, chunk, and embed a book into the local vector DB."""
    from src.vector_db import preprocessing_pipeline

    with console.status("[bold cyan]Parsing, chunking, and embedding...[/bold cyan]", spinner="dots"):
        result = asyncio.run(preprocessing_pipeline(book_genre=book_genre, book_name=book_name, end_page=end_page))
    typer.echo(result)


@content_app.command("run")
def content_run(
    query: str,
    book_title: str = typer.Option(..., help="Book this run is for."),
    step: str = typer.Option(
        "call_expert_builder_agent",
        help=(
            "Director active_agent step: call_book_selection_agent, "
            "call_expert_builder_agent, call_script_drafter_agent, "
            "edit_prompts_skills, review_expert_profile, human_review, "
            "get_lessons_learned, full_flexibility."
        ),
    ),
    thread_id: Optional[str] = typer.Option(None, help="Resume a specific content thread instead of this book's last one."),
):
    """Drive the content director for one turn. Prompts for approve/reject if
    the run reaches script review."""
    from src.agents.content_specialists.director import director_agent

    tid = resolve_thread_id(key=book_title, tier="content", thread_id=thread_id)
    config = {"configurable": {"thread_id": tid}}

    sub_threads = {
        "book_selection": f"{tid}::book_selection",
        "expert_builder": f"{tid}::expert_builder",
        "script_drafter": f"{tid}::script_drafter",
    }
    with track_tokens(director_agent, tid, sub_threads) as usage:
        with console.status("[bold cyan]Running...[/bold cyan]", spinner="dots"):
            outcome = director_agent.invoke(
                {"messages": [("user", query)], "active_agent": step, "book_title": book_title},
                config=config,
            )
        outcome = resolve_interrupts(director_agent, outcome, config)
    typer.echo(outcome["messages"][-1].content)
    render_usage(usage)


@production_app.command("run")
def production_run(
    book_title: str = typer.Option(..., help="Book this run is for."),
    expert_name: str = typer.Option(..., help="Expert persona name used in the script."),
    script: Optional[str] = typer.Option(None, help="Path to script.md (defaults to data/<slug>/script.md, where content run writes it)."),
    feedback: str = typer.Option("", help="Feedback to apply on a revision pass."),
    thread_id: Optional[str] = typer.Option(None, help="Resume a specific production thread instead of this book's last one."),
):
    """Generate episode audio from a drafted script and review it. Loops on
    revision until approved."""
    from src.agents.content_specialists.utils import get_book_path
    from src.agents.production_specialists.speech_generation import speech_gen_workflow

    script_path = script or f"data/{get_book_path(book_title)}/script.md"
    tid = resolve_thread_id(key=book_title, tier="production", thread_id=thread_id)
    config = {"configurable": {"thread_id": tid}}

    sub_threads = {"audio_engineer": f"{tid}:audio_engineer"}
    with track_tokens(speech_gen_workflow, tid, sub_threads) as usage:
        with console.status("[bold cyan]Generating audio...[/bold cyan]", spinner="dots"):
            outcome = speech_gen_workflow.invoke(
                {
                    "book_title": book_title,
                    "expert_name": expert_name,
                    "script": script_path,
                    "audio_result": "",
                    "feedback": feedback,
                },
                config=config,
            )
        outcome = resolve_interrupts(speech_gen_workflow, outcome, config)
    typer.echo(outcome.get("lessons_learned") or outcome.get("status", "done"))
    render_usage(usage)


@distribution_app.command("run")
def distribution_run(
    book_title: str = typer.Option(..., help="Book this run is for."),
    query: str = typer.Option("Prepare the podcast episode for publishing", help="Instruction for the distribution director."),
    script_path: Optional[str] = typer.Option(None, help="Path to script.md (defaults to data/<slug>/script.md)."),
    step: str = typer.Option(
        "call_sm_writer_agent",
        help="Director active_agent step: call_sm_writer_agent, call_publisher_agent, edit_prompts, review_post, get_lessons_learned.",
    ),
    thread_id: Optional[str] = typer.Option(None, help="Resume a specific distribution thread instead of this book's last one."),
):
    """Drive the distribution director (social post + publishing). Fully
    automatic — the review_post step is LLM-adjudicated, no approval prompt."""
    from src.agents.content_specialists.utils import get_book_path
    from src.agents.distribution_specialists.director import director_agent

    path = script_path or f"data/{get_book_path(book_title)}/script.md"
    tid = resolve_thread_id(key=book_title, tier="distribution", thread_id=thread_id)
    config = {"configurable": {"thread_id": tid}}

    sub_threads = {
        "sm_writer": f"{tid}::sm_writer_agent",
        "publisher": f"{tid}::publisher_agent",
    }

    async def _run():
        async with atrack_tokens(director_agent, tid, sub_threads) as usage:
            with console.status("[bold cyan]Running...[/bold cyan]", spinner="dots"):
                outcome = await director_agent.ainvoke(
                    {"messages": [("user", query)], "active_agent": step, "script_path": path},
                    config=config,
                )
        return outcome, usage

    outcome, usage = asyncio.run(_run())
    typer.echo(outcome["messages"][-1].content)
    render_usage(usage)


@skills_app.command("convert-traces")
def skills_convert_traces(
    namespace: str = typer.Argument(..., help="content_traces | production_traces | distribution_traces"),
    book_title: str = typer.Option(..., help="Book whose traces to convert."),
):
    """Turn saved successful traces into reusable skill files."""
    from src.skill_converter import convert_to_skill

    with console.status("[bold cyan]Converting traces into skills...[/bold cyan]", spinner="dots"):
        convert_to_skill(skill_name=namespace, book_title=book_title)
    typer.echo("Done.")


_CHECKPOINT_DBS = {
    "content": "checkpoints/content_checkpoints.db",
    "production": "checkpoints/production_checkpoints.db",
    "distribution": "checkpoints/distribution_checkpoints.db",
}


@maintenance_app.command("prune-checkpoints")
def maintenance_prune_checkpoints(
    db: str = typer.Option("all", help="content | production | distribution | all"),
):
    """Delete checkpoint threads whose latest snapshot is older than 30 days."""
    from src.prune_checkpoints import prune_checkpoints

    targets = _CHECKPOINT_DBS.values() if db == "all" else [_CHECKPOINT_DBS[db]]
    for path in targets:
        prune_checkpoints(path)
        typer.echo(f"Pruned {path}")


if __name__ == "__main__":
    app()
