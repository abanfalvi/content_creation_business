"""Central registry of the OpenRouter model each agent runs on.

Swap a model here rather than in the agent file that uses it.
"""

# Content specialists
BOOK_SELECTION_MODEL = "inclusionai/ling-3.0-flash"
EXPERT_BUILDER_MODEL = "qwen/qwen3.7-flash"
SCRIPT_DRAFTER_MODEL = "qwen/qwen3.7-flash"
DIRECTOR_MODEL = "deepseek/deepseek-v4-flash"

# Production specialists
AUDIO_ENGINEER_MODEL = "xiaomi/mimo-v2.5" # google/gemini-2.5-flash-lite

# Distribution specialists
SM_WRITER_MODEL = "qwen/qwen3.7-flash"
PUBLISHER_MODEL = "nvidia/nemotron-3.5-lightning"
DISTRIBUTION_DIRECTOR_MODEL = "dots-studio/dots-3-note-preview:free"

# Compressor Model
COMPRESSOR_MODEL = "inclusionai/ling-3.0-flash"

# Lessons Learned Extractor Model
LL_EXTRACTOR_AGENT = "deepseek/deepseek-v4-flash"

# Successful traces to skill converter model
SKILL_CONVERTER_MODEL = "cohere/north-mini-code:free"