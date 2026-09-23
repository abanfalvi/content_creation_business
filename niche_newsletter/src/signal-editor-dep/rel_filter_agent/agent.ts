import { MODELS } from "../../models.js";
import { RelFilterAgentState } from "./state.js";
import { filteringTools } from "./tools.js";
import { onRetry } from "../../shared/on_error.js";

import {
    createAgent,
    createMiddleware,
    modelFallbackMiddleware,
    modelRetryMiddleware,
    dynamicSystemPromptMiddleware,
    toolErrorMiddleware,
    type AnyAgentMiddleware,
    type ToolCallRequest
} from "langchain";
import { ChatOpenRouter } from "@langchain/openrouter";
import { readFile } from 'fs/promises';

import dotenv from 'dotenv';

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const relFilterModel = new ChatOpenRouter({
    model: MODELS.RELEVANCE_FILTER_AGENT,
    temperature: .2,
    maxTokens: 4096,
    maxRetries: 2
})

const SYSTEM_PROMPT = await readConfig("src/signal-editor-dep/rel_filter_agent/SYSTEM_PROMPT.md")

const modelCallRetryMiddleware = modelRetryMiddleware({
  maxRetries: 3,
  retryOn: (error) =>
    error.message === "terminated" ||
    error.name === "TimeoutError" ||
    error.name === "NetworkError" ||
    error instanceof TypeError,
  backoffFactor: 1.5,
  initialDelayMs: 1000,
  onFailure: "continue",
}) as AnyAgentMiddleware;


export const relFilterAgent = createAgent({
    model: relFilterModel,
    tools: filteringTools,
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry})
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: RelFilterAgentState,
})