import { MODELS } from "../../models.js";
import { EditorAgentState } from "./state.js";
import { editorTools } from "./tools.js";
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

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const editorModel = new ChatOpenRouter({
    model: MODELS.EDITOR_AGENT,
    temperature: .2,
    maxTokens: 4096,
    maxRetries: 2
})

const SYSTEM_PROMPT = await readConfig("src/signal-editor-dep/editor_agent/SYSTEM_PROMPT.md")

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

const notionUsersPiiGuard = createMiddleware({
  name: "userPiiGuardMiddleware",

  wrapToolCall: async (request, handler) => {
    const result = await handler(request);
    if (request.toolCall.name !== "notion-get-users" || !(result instanceof ToolMessage)) {
      return result;
    }
    const content = typeof result.content === "string" ? result.content : JSON.stringify(result.content);
    const redacted = applyStrategy(content, detectEmail(content), "redact", "email");
    return new ToolMessage({ ...result, content: redacted });
  },
});

export const editorAgent = createAgent({
    model: editorModel,
    tools: editorTools,
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
        notionUsersPiiGuard
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: EditorAgentState,
});