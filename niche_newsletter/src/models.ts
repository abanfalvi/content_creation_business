// List of model names to use throughout the project
import { OpikCallbackHandler } from "opik-langchain";
import { installOpenRouterErrorCapture } from "./shared/openrouter_errors.js";

// Every agent imports this module, so this covers all ChatOpenRouter calls.
installOpenRouterErrorCapture();

export const opikHandler = new OpikCallbackHandler({projectName: "niche_newsletter"});
export const MODELS = {
    SIGNAL_EDITOR_MANAGER: "deepseek/deepseek-v4-flash-0731",
    EDITOR_AGENT: "inclusionai/ling-3.0-flash-vl",
    RELEVANCE_FILTER_AGENT: "inclusionai/ling-3.0-flash",
    RESEARCH_AGENT: "inclusionai/ling-3.0-flash-vl",
    USE_CASE_WRITER_AGENT: "inclusionai/ling-3.0-flash-vl",
    IMAGE_GENERATION_MODEL: "recraft/recraft-v4.1-flash",

    DISTRIBUTION_MANAGER: "dots-studio/dots-3-note-preview:free",
    USER_OUTREACH_AGENT: "inclusionai/ling-3.0-flash-vl",
    SM_AGENT: "qwen/qwen3.7-flash",

    DIG_PROD_CREATOR_MODEL: "openai/gpt-6-luna",

    MEMORY_MANAGEMENT_MODEL: "qwen/qwen3.7-flash",
    OVERLAP_JUDGE_MODEL: "typesafe/jev-1.13",

    MAIN_ORCHESTRATOR_MODEL: "dots-studio/dots-3-note-preview:free",

    ORCHESTRATOR_FALLBACK_1: "inclusionai/ling-3.1-flash",
    ORCHESTRATOR_FALLBACK_2: "qwen/qwen3.7-flash",

} as const;

