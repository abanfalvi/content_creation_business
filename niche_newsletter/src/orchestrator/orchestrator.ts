import { onRetry } from "../shared/on_error.js";
import { z } from "zod";
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
import { AIMessage, HumanMessage, ToolMessage } from "@langchain/core/messages";
import { readFile } from 'fs/promises';

import dotenv from 'dotenv';
import { MODELS } from "../models.js";
import { OrchestratortState, type AgentStateType } from "./state.js";
import { orchestratorTools } from "./tools.js";
import { checkpointer } from "./checkpointer.js";

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

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

const memoryPhaseMiddleware = createMiddleware({
  name: "MemoryPhase",
  stateSchema: z.object({ memoryPhase: z.boolean().default(false) }),

  wrapModelCall: async (request, handler) => {
    const tools = request.tools.filter( t =>
      request.state.memoryPhase
      ? t.name === "call_memory_management_agent"
      : t.name !== "call_memory_management_agent"
    );
    return handler({...request, tools})
  },

  afterModel: {
    canJumpTo: ["model"],
    hook: (state) => {
      const last = state.messages.at(-1) as AIMessage;
      if (state.memoryPhase || last.tool_calls?.length) return;
      return {
        memoryPhase: true,
        messages: [new HumanMessage(
          "The task is finished. Decide whether anything from this run is worth saving to memory. " +
          "If so, call call_memory_management_agent; otherwise reply 'nothing to save'.")],
        jumpTo: "model"
      }
    }
  }
})


export const orchestratorAgent = createAgent({
    model: orchestratorModel,
    tools: orchestratorTools,
    middleware: [
        // memoryPhaseMiddleware,
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: OrchestratortState,
    checkpointer: checkpointer
});