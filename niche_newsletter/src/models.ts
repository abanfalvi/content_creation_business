// List of model names to use throughout the project
import { OpikCallbackHandler } from "opik-langchain";

export const opikHandler = new OpikCallbackHandler({projectName: "niche_newsletter"});
export const MODELS = {
    SIGNAL_EDITOR_MANAGER: "deepseek/deepseek-v4-flash-0731",
    EDITOR_AGENT: "qwen/qwen3.7-flash",
    RELEVANCE_FILTER_AGENT: "inclusionai/ling-3.0-flash",
    RESEARCH_AGENT: "nex-agi/nex-n2.5-mini:free",
    USE_CASE_WRITER_AGENT: "nex-agi/nex-n2.5-pro:free",
    IMAGE_GENERATION_MODEL: "meta/muse-image",

    DISTRIBUTION_MANAGER: "dots-studio/dots-3-note-preview:free",
    USER_OUTREACH_AGENT: "nex-agi/nex-n2.5-pro:free",
    SM_AGENT: "qwen/qwen3.7-flash",

    DIG_PROD_CREATOR_MODEL: "poolside/laguna-s-2.1",

    MEMORY_MANAGEMENT_MODEL: "inclusionai/ling-3.0-flash",

    MAIN_ORCHESTRATOR_MODEL: "dots-studio/dots-3-note-preview:free"
} as const;

