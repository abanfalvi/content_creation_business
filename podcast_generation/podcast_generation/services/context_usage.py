import json
import logging
import os
from typing import Sequence

import httpx
from langchain_core.messages import AIMessage, BaseMessage

log = logging.getLogger(__name__)

DEFAULT_CONTEXT_WINDOW = 200_000
MODELS_URL = "https://openrouter.ai/api/v1/models"
CHARS_PER_TOKEN = 4

_windows: dict[str, int] = {}


async def context_window(model: str) -> int:
    """Context window of an OpenRouter model. CHAT_CONTEXT_WINDOW overrides it; any lookup failure gives a default."""
    override = os.environ.get("CHAT_CONTEXT_WINDOW", "")
    if override.isdigit() and int(override) > 0:
        return int(override)
    if model not in _windows:
        _windows[model] = await _lookup(model)
    return _windows[model]


async def _lookup(model: str) -> int:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(MODELS_URL)
            response.raise_for_status()
        listed = {m["id"]: m.get("context_length") for m in response.json().get("data", [])}
        return listed.get(model) or listed.get(model.removesuffix(":free")) or DEFAULT_CONTEXT_WINDOW
    except Exception:  # noqa: BLE001 - the meter is cosmetic; never let it break a chat
        log.warning("Could not look up the context window of %s; assuming %d", model, DEFAULT_CONTEXT_WINDOW)
        return DEFAULT_CONTEXT_WINDOW


def _estimate(message: BaseMessage) -> int:
    content = message.content if isinstance(message.content, str) else json.dumps(message.content)
    return -(-len(content) // CHARS_PER_TOKEN)


def count_context_tokens(messages: Sequence[BaseMessage]) -> int:
    """Tokens in the conversation: the provider-reported total of the latest reply (prompt + completion, which is
    what the next call starts from) plus an estimate for anything after it; with no report, an estimate of everything."""
    for i in range(len(messages) - 1, -1, -1):
        message = messages[i]
        reported = (message.usage_metadata or {}).get("total_tokens") if isinstance(message, AIMessage) else None
        if reported:
            return reported + sum(_estimate(m) for m in messages[i + 1:])
    return sum(_estimate(m) for m in messages)
