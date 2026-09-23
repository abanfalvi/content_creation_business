import { MODELS } from "../../models.js";
import { SMAgentState, type AgentStateType } from "./state.js";
import { SMTools } from "./tools.js";
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
import { checkpointer } from "../checkpointer.js";

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const SMModel = new ChatOpenRouter({
    model: MODELS.SM_AGENT,
    temperature: .2,
    maxTokens: 4096,
    maxRetries: 2
})

const SYSTEM_PROMPT = await readConfig("src/distribution-dep/sm_agent/SYSTEM_PROMPT.md")

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

const toolsConfig = createMiddleware({
  name: "apply_tool_config",
  stateSchema: SMAgentState.pick({loadedTools: true}),

  // wrapModelCall: async (request, handler) => {
  //   const availableTools = request.state.loadedTools
  //   return await handler({...request, tools: availableTools})
  // },
});

const bufferUserPiiGuard = createMiddleware({
  name: "userPiiGuardMiddleware",

  wrapToolCall: async (request, handler) => {
    const result = await handler(request);
    if (request.toolCall.name !== "get_account" || !(result instanceof ToolMessage)) {
      return result;
    }
    const content = typeof result.content === "string" ? result.content : JSON.stringify(result.content);
    const redacted = applyStrategy(content, detectEmail(content), "redact", "email");
    return new ToolMessage({ ...result, content: redacted });
  },
});

// Gates every create_post call on manager approval — the graph pauses here (via
// runtime.interrupt) until the distribution manager resumes it with a review decision.
// Structural on purpose: the model can't accidentally publish/schedule without review,
// since it's not the model's call whether to ask for one.
const reviewGateMiddleware = createMiddleware({
  name: "reviewGateMiddleware",

  wrapToolCall: async (request, handler) => {
    if (request.toolCall.name !== "create_post") return handler(request);

    const decision = request.runtime.interrupt!({
      type: "sm_post_review",
      args: request.toolCall.args,
    }) as { approved: boolean; feedback?: string };

    if (!decision.approved) {
      return new ToolMessage({
        content: `Post not approved by manager review${decision.feedback ? `: ${decision.feedback}` : "."}`,
        tool_call_id: request.toolCall.id ?? "",
      });
    }

    return handler(request);
  },
});

export const SMAgent = createAgent({
    model: SMModel,
    tools: SMTools,
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
        bufferUserPiiGuard,
        reviewGateMiddleware,
        // toolsConfig
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: SMAgentState,
    checkpointer: checkpointer
});