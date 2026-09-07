from typing import Literal
from pathlib import Path
import logging, json
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass

Path("logs").mkdir(exist_ok=True)
logger = logging.getLogger("token_usage")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler("logs/token_usage.jsonl", maxBytes=1_000_000, backupCount=5)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)

def log_token_usage(
        department: Literal["persona_identity", "content_production", "engagement_community"], 
        agent: str, 
        thread_id: str, 
        input_tokens: int, 
        output_tokens: int
    ) -> None:
    logger.info(json.dumps(
        {
            "department": department, 
            "agent": agent, 
            "thread_id": thread_id, 
            "input_tokens": input_tokens, 
            "output_tokens": output_tokens
        }
    ))

    return None

@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

def sum_usage(messages: list) -> TokenUsage:
    usage = TokenUsage()
    for message in messages:
        meta = getattr(message, "usage_metadata", None)
        if meta:
            usage.input_tokens += meta.get("input_tokens", 0)
            usage.output_tokens += meta.get("output_tokens", 0)
    return usage