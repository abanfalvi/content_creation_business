import opik
import os 

opik.configure(api_key=os.environ.get("OPIK_API_KEY"), workspace="dreadnought0073", project_name="ai_influencer_agency", install_mcp=False)

# Persona & Identity Department
CHARACTER_DESIGN_AGENT="upstage/solar-pro4"
PERSONALITY_AGENT="xiaomi/mimo-v2.5"
BACKSTORY_AGENT="upstage/solar-pro4"
IDENTITY_MANAGER="inclusionai/ling-3.0-flash"
IMAGE_PROMPT_GEN_MODEL="upstage/solar-pro4"

# Fallback trio (upstage/solar-pro4, qwen/qwen3.7-flash, deepseek/deepseek-v4-flash-0731)
# circles between each other: whichever of the three is a model's primary, the
# other two are its fallbacks. GLM- and Ling-family models are intentionally
# left without a fallback for now.
SOLAR_FALLBACK_MODEL="upstage/solar-pro4"
PERSONA_FALLBACK_MODEL_1="qwen/qwen3.7-flash"
PERSONA_FALLBACK_MODEL_2="deepseek/deepseek-v4-flash-0731"

# Shared fallback for every xiaomi/mimo-v2.5-based model
MIMO_FALLBACK_MODEL="thinkingmachines/inkling-small"

# Content Production Department
IMAGE_GEN_MODEL="meta/muse-image"
VIDEO_GEN_MODEL="fal-ai/ltx-video/image-to-video"
LIPSYNC_MODEL="fal-ai/sync-lipsync/v2" # fal ai model
SM_CONTENT_WRITER_AGENT="xiaomi/mimo-v2.5"
CONTENT_CALENDAR_AGENT="upstage/solar-pro4"
CONTENT_PRODUCTION_MANAGER="xiaomi/mimo-v2.5"
SAFETY_MODEL="qwen/qwen3.7-flash"

# Engagement & Community Department
REPLY_AGENT="upstage/solar-pro4"
FOLLOWER_GROWTH_HEALTH_AGENT="upstage/solar-pro4"
ENGAGEMENT_MANAGER="z-ai/glm-5.3-flash"

# Memory Manager
MEMORY_MANAGEMENT_MODEL="upstage/solar-pro4"

# Auditor
AUDITOR_MODEL="qwen/qwen3.7-flash"

# Orchestrator
ORCHESTRATOR="upstage/solar-pro4"

# Skill Converter
SKILL_CONVERTER_MODEL="upstage/solar-pro4"

# Input Guard Model (via Mistral)
PROMPT_GUARD="mistral-moderation-2603"