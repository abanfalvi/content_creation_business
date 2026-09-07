"""Per-turn input/output token accounting for the orchestrator conversation.

ChatOpenRouter stamps every AIMessage with `usage_metadata` (input/output
tokens), and that survives checkpointing — so this reads it back out of the
thread's persisted state rather than adding new instrumentation at the
model-call level. Snapshotting the message count before a turn and diffing
after gives that turn's usage, not the thread's lifetime total (threads are
reused across separate CLI sessions)."""
from contextlib import asynccontextmanager
from ..agents.utils import TokenUsage, sum_usage



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
        turn_usage = sum_usage(messages[before_count:])
        usage.input_tokens = turn_usage.input_tokens
        usage.output_tokens = turn_usage.output_tokens
