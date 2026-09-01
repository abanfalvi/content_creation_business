"""Per-turn input/output token accounting for the orchestrator conversation.

ChatOpenRouter stamps every AIMessage with `usage_metadata` (input/output
tokens), and that survives checkpointing — so this reads it back out of the
thread's persisted state rather than adding new instrumentation at the
model-call level. Snapshotting the message count before a turn and diffing
after gives that turn's usage, not the thread's lifetime total (threads are
reused across separate CLI sessions)."""
from contextlib import asynccontextmanager
from dataclasses import dataclass

from rich.table import Table


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


@asynccontextmanager
async def atrack_tokens(agent, thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await agent.aget_state(config)
    before_count = len(snapshot.values.get("messages", [])) if snapshot.values else 0

    usage = TokenUsage()
    try:
        yield usage
    finally:
        snapshot = await agent.aget_state(config)
        messages = snapshot.values.get("messages", []) if snapshot.values else []
        turn_usage = _sum_usage(messages[before_count:])
        usage.input_tokens = turn_usage.input_tokens
        usage.output_tokens = turn_usage.output_tokens


def usage_table(session_total: TokenUsage, last_turn: TokenUsage) -> Table:
    table = Table(title="Token usage", expand=True)
    table.add_column("Scope")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Total", justify="right")
    table.add_row("Last turn", str(last_turn.input_tokens), str(last_turn.output_tokens), str(last_turn.total_tokens))
    table.add_row(
        "[bold]Session[/bold]",
        f"[bold]{session_total.input_tokens}[/bold]",
        f"[bold]{session_total.output_tokens}[/bold]",
        f"[bold]{session_total.total_tokens}[/bold]",
    )
    return table
