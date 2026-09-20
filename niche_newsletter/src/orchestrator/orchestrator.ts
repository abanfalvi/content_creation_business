import { onRetry } from "../shared/on_error.js";

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
import { MODELS } from "../models.js";
import { OrchestratortState, type AgentStateType } from "./state.js";
import { orchestratorTools } from "./tools.js";
import { checkpointer } from "./checkpointer.js";

dotenv.config();

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const orchestratorModel = new ChatOpenRouter({
    model: MODELS.MAIN_ORCHESTRATOR_MODEL,
    temperature: .2,
    maxTokens: 2048,
    maxRetries: 2,
})

const SYSTEM_PROMPT = await readConfig("src/orchestrator/SYSTEM_PROMPT.md")

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


export const orchestratorAgent = createAgent({
    model: orchestratorModel,
    tools: orchestratorTools,
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: OrchestratortState,
    checkpointer: checkpointer
});