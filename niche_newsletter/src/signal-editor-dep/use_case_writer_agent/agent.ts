import { MODELS } from "../../models.js";
import { UseCaseWriterAgentState } from "./state.js";
import { useCaseWriterTools } from "./tools.js";
import { onRetry } from "../../shared/on_error.js";

import {
    createAgent,
    toolCallLimitMiddleware,
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

dotenv.config();

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const userCaseWriterModel = new ChatOpenRouter({
    model: MODELS.USE_CASE_WRITER_AGENT,
    temperature: .2,
    maxTokens: 4096,
    maxRetries: 2
})

const SYSTEM_PROMPT = await readConfig("src/signal-editor-dep/use_case_writer_agent/SYSTEM_PROMPT.md")

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

const searchVideosLimitMiddleware = toolCallLimitMiddleware({
  toolName: "search_videos",
  runLimit: 7,
  exitBehavior: "continue",
} as never) as AnyAgentMiddleware;

export const userCaseWriterAgent = createAgent({
    model: userCaseWriterModel,
    tools: useCaseWriterTools,
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
        searchVideosLimitMiddleware
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: UseCaseWriterAgentState,
});