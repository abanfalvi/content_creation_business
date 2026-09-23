import { MODELS } from "../../models.js";
import { DigProdCreationAgentState, type AgentStateType } from "./state.js";
import { productCreationTools } from "./tools.js";
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

const DigProdCreationModel = new ChatOpenRouter({
    model: MODELS.DIG_PROD_CREATOR_MODEL,
    temperature: .2,
    maxTokens: 4096,
    maxRetries: 2
})

const SYSTEM_PROMPT = await readConfig("src/curriculum-dep/dig_prod_creator_agent/SYSTEM_PROMPT.md")

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

const reviewGateMiddleware = createMiddleware({
  name: "reviewGateMiddleware",

  wrapToolCall: async (request, handler) => {
    if (request.toolCall.name !== "finalize_document") return handler(request);

    // Runs before finalize_document's handler, so nothing has happened yet at this
    // point — safe against LangGraph replaying this call from the top on resume.
    const decision = request.runtime.interrupt!({
      type: "pdf_doc_review",
      args: request.toolCall.args,
      documentUrl: (request.state as AgentStateType).pendingDocumentUrl,
    }) as { approved: boolean; feedback?: string };

    if (!decision.approved) {
      // finalize_document's handler never runs, so its sandbox stays alive —
      // the agent's next create_document call reconnects to it instead of
      // starting a fresh one.
      return new ToolMessage({
        content: `Document not approved by manager review${decision.feedback ? `: ${decision.feedback}` : "."} The sandbox is still running — call create_document again with the fix.`,
        tool_call_id: request.toolCall.id ?? "",
      });
    }

    return handler(request);
  },
});

export const DigProdCreationAgent = createAgent({
    model: DigProdCreationModel,
    tools: productCreationTools,
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
        reviewGateMiddleware,
        // toolsConfig
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: DigProdCreationAgentState,
    checkpointer: checkpointer
});