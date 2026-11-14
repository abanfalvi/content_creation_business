"""Central registry of the OpenRouter model each agent runs on.

Swap a model here rather than in the agent file that uses it.

Also owns the Opik setup: agents call `track(graph)` instead of configuring
Opik themselves. Opik is configured through the environment (OPIK_API_KEY and
OPIK_WORKSPACE from `.env`; OPIK_PROJECT_NAME is set in `settings`), so nothing
connects to the network until a trace is actually sent.
"""
from opik.integrations.langchain import OpikTracer, track_langgraph


def track(graph, trace=True):
    """Attach Opik tracing to a compiled LangGraph graph and return it.

    Each graph gets its own OpikTracer: track_langgraph stores the graph's
    structure on the tracer, so a shared tracer would show the last-tracked
    agent's graph on every trace.
    """
    if trace:
        return track_langgraph(graph, OpikTracer())
    else:
        return graph


# Content specialists
BOOK_SELECTION_MODEL = "inclusionai/ling-3.0-flash"
EXPERT_BUILDER_MODEL = "minimax/minimax-m3.1-flash"
SCRIPT_DRAFTER_MODEL = "minimax/minimax-m3.1-flash"
SCRIPT_PLANNER_MODEL = "minimax/minimax-m3.1-flash"
EVALUATOR_MODEL = "z-ai/glm-5.3-flash"
DIGEST_MODEL = "z-ai/glm-5.3-flash" 
DIRECTOR_MODEL = "deepseek/deepseek-v4-flash-0731"

# Production specialists
AUDIO_ENGINEER_MODEL = "xiaomi/mimo-v2.6" # google/gemini-2.5-flash-lite

# Chat (question answering over the selected sources)
CHAT_MODEL = "deepseek/deepseek-v4-flash-0731"

# Compressor Model
COMPRESSOR_MODEL = "inclusionai/ling-3.0-flash"

# Lessons Learned Extractor Model
LL_EXTRACTOR_AGENT = "deepseek/deepseek-v4-flash-0731"

# Successful traces to skill converter model
SKILL_CONVERTER_MODEL = "cohere/north-mini-code:free"

# Decision model used
DECISION_JUDGE = "parallel/decisions-fast:free"