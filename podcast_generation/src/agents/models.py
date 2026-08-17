"""Central registry of the OpenRouter model each agent runs on.

Swap a model here rather than in the agent file that uses it.
"""

# Content specialists
BOOK_SELECTION_MODEL = "inclusionai/ling-3.0-flash"
EXPERT_BUILDER_MODEL = "qwen/qwen3.7-flash"
SCRIPT_DRAFTER_MODEL = "qwen/qwen3.7-flash"
DIRECTOR_MODEL = "deepseek/deepseek-v4-flash"

# Production specialists
AUDIO_ENGINEER_MODEL = "xiaomi/mimo-v2.5"

# Distribution specialists
SM_WRITER_MODEL = "nvidia/nemotron-3.5-lightning"
PUBLISHER_MODEL = "qwen/qwen3.7-flash"
DISTRIBUTION_DIRECTOR_MODEL = "deepseek/deepseek-v4-flash"

# Compressor Model
COMPRESSOR_MODEL = "inclusionai/ling-3.0-flash"

# Lessons Learned Extractor Model
LL_EXTRACTOR_AGENT = "deepseek/deepseek-v4-flash"