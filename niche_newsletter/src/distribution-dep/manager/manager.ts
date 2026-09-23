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
import { ToolMessage } from "@langchain/core/messages";
import { readFile } from 'fs/promises';

import dotenv from 'dotenv';
import { MODELS } from "../../models.js";
import { ManagerAgentState, type AgentStateType } from "./state.js";
import { managerTools } from "./tools.js";
import { checkpointer } from "../checkpointer.js";

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const distributionManagerModel = new ChatOpenRouter({
    model: MODELS.DISTRIBUTION_MANAGER,
    temperature: .2,
    maxTokens: 2048,
    maxRetries: 2
})

const SYSTEM_PROMPT = await readConfig("src/distribution-dep/manager/SYSTEM_PROMPT.md")

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


export const distributionManagerAgent = createAgent({
    model: distributionManagerModel,
    tools: managerTools,
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: ManagerAgentState,
    checkpointer: checkpointer
});