// List of model names to use throughout the project
import { OpikCallbackHandler } from "opik-langchain";
import { installOpenRouterErrorCapture } from "./shared/openrouter_errors.js";

// Every agent imports this module, so this covers all ChatOpenRouter calls.
installOpenRouterErrorCapture();

export const opikHandler = new OpikCallbackHandler({projectName: "niche_newsletter"});
export const MODELS = {
    SIGNAL_EDITOR_MANAGER: "deepseek/deepseek-v4-flash-0731",
    EDITOR_AGENT: "anthropic/claude-haiku-5.5",
    RELEVANCE_FILTER_AGENT: "inclusionai/ling-3.0-flash",
    RESEARCH_AGENT: "deepseek/deepseek-v4.1-flash",
    USE_CASE_WRITER_AGENT: "deepseek/deepseek-v4.1-flash",
    IMAGE_GENERATION_MODEL: "recraft/recraft-v4.1-flash",

    DISTRIBUTION_MANAGER: "deepseek/deepseek-v4-flash-0731",
    USER_OUTREACH_AGENT: "inclusionai/ling-3.0-flash-vl",
    SM_AGENT: "z-ai/glm-5.3-flash",

    DIG_PROD_CREATOR_MODEL: "openai/gpt-6-luna",

    MEMORY_MANAGEMENT_MODEL: "z-ai/glm-5.3-flash",
    OVERLAP_JUDGE_MODEL: "typesafe/jev-1.13",

    MAIN_ORCHESTRATOR_MODEL: "xiaomi/mimo-v2.6-flash",

    ORCHESTRATOR_FALLBACK_1: "deepseek/deepseek-v4.1-flash",
    ORCHESTRATOR_FALLBACK_2: "poolside/laguna-xs-2.1",

    SKILL_OPTIMIZER_MODEL: "z-ai/glm-5.3-flash",
    TRACE_SUMMARIZER_MODEL: "inclusionai/ling-3.0-flash",

} as const;

