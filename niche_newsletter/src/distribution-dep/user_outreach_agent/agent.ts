import { MODELS } from "../../models.js";
import { UserOutreachAgentState, type AgentStateType } from "./state.js";
import { outreachTools } from "./tools.js";
import { onRetry } from "../../shared/on_error.js";

import {
    createAgent,
    toolCallLimitMiddleware,
    modelFallbackMiddleware,
    applyStrategy,
    detectEmail,
    createMiddleware,
    modelRetryMiddleware,
    piiMiddleware,
    toolErrorMiddleware,
    type AnyAgentMiddleware,
} from "langchain";
import { ChatOpenRouter } from "@langchain/openrouter";
import { readFile } from 'fs/promises';

import dotenv from 'dotenv';

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const OutreachModel = new ChatOpenRouter({
    model: MODELS.USER_OUTREACH_AGENT,
    temperature: .2,
    maxTokens: 2048,
    maxRetries: 2
})

const SYSTEM_PROMPT = await readConfig("src/distribution-dep/user_outreach_agent/SYSTEM_PROMPT.md")

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

export const OutreachAgent = createAgent({
    model: OutreachModel,
    tools: outreachTools,
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: UserOutreachAgentState,
});