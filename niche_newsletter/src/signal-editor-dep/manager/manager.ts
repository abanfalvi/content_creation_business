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

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const editorManagerModel = new ChatOpenRouter({
    model: MODELS.SIGNAL_EDITOR_MANAGER,
    temperature: .2,
    maxTokens: 2048,
    maxRetries: 2
})

const SYSTEM_PROMPT = await readConfig("src/signal-editor-dep/manager/SYSTEM_PROMPT.md")

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

const STEP_CONFIG = {
  flexibleWorkflow: {
    tools: managerTools,
  },
  researchStep: {
    tools: managerTools.filter(t => t.name === "call_research_agent")
  },
  filteringStep: {
    tools: managerTools.filter(t => t.name === "call_rel_filter_agent")
  },
  useCaseStep: {
    tools: managerTools.filter(t => t.name === "call_use_case_writer_agent")
  },
  editingStep: {
    tools: managerTools.filter(t =>
      t.name === "call_editor_agent" ||
      t.name === "review_newsletter" ||
      t.name === "get_post" ||
      t.name === "get_post_content" ||
      t.name === "get_post_footer" ||
      t.name === "list_posts"
    )
  }
}

const applyToolConfig = createMiddleware({
  name: "applyToolConfigMiddleware",
  stateSchema: ManagerAgentState.pick({currentStep: true}),

  wrapModelCall: async (request, handler) => {
    const step = request.state.currentStep;
    const config = STEP_CONFIG[step as keyof typeof STEP_CONFIG];

    return handler({
      ...request,
      tools: config?.tools ?? request.tools,
    });
  },
});

export const editorManagerAgent = createAgent({
    model: editorManagerModel,
    tools: managerTools,
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
        applyToolConfig
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: ManagerAgentState,
});