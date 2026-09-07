import os
import sys
import psycopg
import asyncio 

from src.cli.state import resolve_thread_id, get_default_influencer

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


Path("logs").mkdir(exist_ok=True)
logger = logging.getLogger("scheduled_run")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler("logs/scheduled_run.log", maxBytes=1_000_000, backupCount=5)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)

def _content_to_text(content) -> str:

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


scheduled_instruction = "Create today's posts and publish or schedule them"

def check_postgres_available() -> None:
    uri = os.environ.get("POSTGRES_URI")
    if not uri:
        print("POSTGRES_URI is not set in the environment.", file=sys.stderr)
        sys.exit(1)
    try:
        with psycopg.connect(uri, connect_timeout=5):
            pass
    except psycopg.OperationalError as exc:
        print(f"Postgres isn't reachable ({exc}). Is `docker compose up -d` running?", file=sys.stderr)
        sys.exit(1)

async def run_scheduled_job():
    from src.orchestration.agent import get_orchestrator_agent
    thread_id = resolve_thread_id("scheduled")
    agent = await get_orchestrator_agent()
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await agent.aget_state(config)
    values = snapshot.values or {}
    influencer_name = values.get("influencer_name")
    if influencer_name is None:
        default_slug = get_default_influencer()
        if default_slug is None:
            logger.error("no default influencer set — run `influencer_agency influencer` first")
            return
        await agent.aupdate_state(config, {"influencer_name": default_slug})
        influencer_name = default_slug
    seen = 0
    prompt = f"[Active influencer: {influencer_name}]\n\n{scheduled_instruction}" if influencer_name else scheduled_instruction
    try:
        async for mode, data in agent.astream(
            {"messages": [("user", prompt)]}, config=config, stream_mode=["values", "custom"]
        ):
            if mode == "values":
                outcome = data
                messages = data.get("messages", [])
                for message in messages[seen:]:
                    if getattr(message, "tool_calls", None):
                        for call in message.tool_calls:
                            args_text = ", ".join(f"{k}={v!r}" for k, v in (call.get("args") or {}).items())
                            logger.info("tool call: %s(%s)", call.get("name", "tool"), args_text)
                seen = len(messages)
                if not outcome:
                    logger.error("orchestrator finished without returning a response")
                else:
                    reply = _content_to_text(outcome["messages"][-1].content).strip()
                    logger.info("final reply: %s", reply or "(empty)")
    except Exception as e:
        logger.exception(e)


async def main():
    check_postgres_available()
    try:
        await run_scheduled_job()
    finally:
        from src.orchestration.utils import close_checkpointer as orchestrator_close_checkpointer
        from src.agents.content_production.utils import close_checkpointer as production_close_checkpointer
        await orchestrator_close_checkpointer()
        await production_close_checkpointer()

if __name__ == "__main__":
    main_result = asyncio.run(main())
