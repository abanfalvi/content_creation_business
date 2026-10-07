import { MODELS } from "../../models.js";
import { EditorAgentContext, EditorAgentState, type AgentStateType } from "./state.js";
import { editorTools } from "./tools.js";
import { onRetry } from "../../shared/on_error.js";
import { createVerifyEndRunMiddleware } from "../../shared/verify_end_run.js";

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
import { request } from "http";

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const editorModel = new ChatOpenRouter({
    model: MODELS.EDITOR_AGENT,
    temperature: .2,
    maxTokens: 20000,
    maxRetries: 2
})

if (!process.env.BEEHIIV_PUBLICATION_ID) {
    throw new Error("BEEHIIV_PUBLICATION_ID is not set — add it to .env (find it with beehiiv's list_publications).");
}
const SYSTEM_PROMPT = (await readConfig("src/signal-editor-dep/editor_agent/SYSTEM_PROMPT_NOTION.md"))
    .replaceAll("{{BEEHIIV_PUBLICATION_ID}}", process.env.BEEHIIV_PUBLICATION_ID);

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

// The manager passes the orchestrator's agreed outline as run context. It is not in state (nothing checkpoints it),
// so it is added to the system prompt on every model call of the run.
const addPromptingTechniqueGuideMiddleware = createMiddleware({
  name: "add_prompting_techniques_guide_middlware",
  contextSchema: EditorAgentContext,

  wrapModelCall: (request, handler) => {
    const guide = request.runtime.context?.promptingGuide;
    if (!guide) return handler(request);
    return handler({
      ...request,
      systemMessage: request.systemMessage.concat(
        "\n\n# Detailed outline for this post\n\n" +
        "This post is about a prompting technique and the outline below was already agreed with the user. " +
        "Write the post from it: keep its sections in order, teach each technique as described, and use the example prompts exactly as written. " +
        "Don't add techniques, claims or examples that aren't in it, and don't research the topic.\n\n" +
        guide
      ),
    });
  },
})

export const editorAgent = createAgent({
    model: editorModel,
    tools: editorTools,
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
        notionUsersPiiGuard,
        addPromptingTechniqueGuideMiddleware,
        createVerifyEndRunMiddleware(),
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: EditorAgentState,
    contextSchema: EditorAgentContext
});