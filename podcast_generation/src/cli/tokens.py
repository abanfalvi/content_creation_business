"""Per-run input/output token accounting.

Each director calls its specialists as tools on their own checkpointed
sub-threads (e.g. f"{thread_id}::script_drafter") rather than the director's
own thread, so a run's total token usage is spread across several threads.
ChatOpenRouter already stamps every AIMessage with `usage_metadata`
(input/output/total tokens), and that survives checkpointing — so this reads
it back out of each thread's persisted state rather than adding new
instrumentation at the model-call level. Snapshotting the message count
before a run and diffing after gives this run's usage, not the thread's
lifetime total (threads are reused across separate CLI invocations)."""
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass

from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _sum_usage(messages: list) -> TokenUsage:
    usage = TokenUsage()
    for message in messages:
        meta = getattr(message, "usage_metadata", None)
        if meta:
            usage.input_tokens += meta.get("input_tokens", 0)
            usage.output_tokens += meta.get("output_tokens", 0)
    return usage


@contextmanager
def track_tokens(agent, thread_id: str, sub_threads: dict[str, str] | None = None):
    sub_threads = sub_threads or {}
    threads = {"main": thread_id, **sub_threads}

    before_counts = {}
    for label, tid in threads.items():
        snapshot = agent.get_state({"configurable": {"thread_id": tid}})
        before_counts[label] = len(snapshot.values.get("messages", [])) if snapshot.values else 0

    result: dict[str, TokenUsage] = {label: TokenUsage() for label in threads}
    try:
        yield result
    finally:
        for label, tid in threads.items():
            snapshot = agent.get_state({"configurable": {"thread_id": tid}})
            messages = snapshot.values.get("messages", []) if snapshot.values else []
            usage = _sum_usage(messages[before_counts[label]:])
            result[label].input_tokens = usage.input_tokens
            result[label].output_tokens = usage.output_tokens


@asynccontextmanager
async def atrack_tokens(agent, thread_id: str, sub_threads: dict[str, str] | None = None):
    sub_threads = sub_threads or {}
    threads = {"main": thread_id, **sub_threads}

    before_counts = {}
    for label, tid in threads.items():
        snapshot = await agent.aget_state({"configurable": {"thread_id": tid}})
        before_counts[label] = len(snapshot.values.get("messages", [])) if snapshot.values else 0

    result: dict[str, TokenUsage] = {label: TokenUsage() for label in threads}
    try:
        yield result
    finally:
        for label, tid in threads.items():
            snapshot = await agent.aget_state({"configurable": {"thread_id": tid}})
            messages = snapshot.values.get("messages", []) if snapshot.values else []
            usage = _sum_usage(messages[before_counts[label]:])
            result[label].input_tokens = usage.input_tokens
            result[label].output_tokens = usage.output_tokens


def render_usage(usage: dict[str, TokenUsage]) -> None:
    table = Table(title="Token usage for this run")
    table.add_column("Agent")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Total", justify="right")

    total = TokenUsage()
    for label, tokens in usage.items():
        table.add_row(label, str(tokens.input_tokens), str(tokens.output_tokens), str(tokens.total_tokens))
        total.input_tokens += tokens.input_tokens
        total.output_tokens += tokens.output_tokens

    table.add_row("[bold]total[/bold]", f"[bold]{total.input_tokens}[/bold]", f"[bold]{total.output_tokens}[/bold]", f"[bold]{total.total_tokens}[/bold]")
    console.print(table)
