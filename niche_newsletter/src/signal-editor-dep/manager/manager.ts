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
import { HumanMessage, ToolMessage } from "@langchain/core/messages";
import { readFile } from 'fs/promises';

import dotenv from 'dotenv';
import { MODELS } from "../../models.js";
import { ManagerAgentState, ManagerAgentContext, type AgentStateType } from "./state.js";
import { managerTools } from "./tools.js";
import { checkpointer } from "../checkpointer.js";
import { createVerifyEndRunMiddleware } from "../../shared/verify_end_run.js";

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const editorManagerModel = new ChatOpenRouter({
    model: MODELS.SIGNAL_EDITOR_MANAGER,
    temperature: .2,
    maxTokens: 8192,
    maxRetries: 2,
    provider: {
      sort: "price"
    }
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
    tools: managerTools.filter(t => t.name === "call_rel_filter_agent" || t.name === "call_research_agent")
  },
  useCaseStep: {
    tools: managerTools.filter(t => t.name === "call_use_case_writer_agent" || t.name === "call_rel_filter_agent")
  },
  editingStep: {
    tools: managerTools.filter(t =>
      t.name === "call_editor_agent" ||
      t.name === "call_rel_filter_agent" ||
      t.name === "call_use_case_writer_agent" ||
      t.name === "review_newsletter" ||
      t.name === "notion-search" ||
      t.name === "notion-fetch"
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

// The editor agent receives the outline directly (call_editor_agent passes it as context). The manager gets it
// too so it can review the draft against it, instead of judging it against research it never ran.
const showPromptingGuide = createMiddleware({
  name: "showPromptingGuideMiddleware",
  contextSchema: ManagerAgentContext,

  wrapModelCall: (request, handler) => {
    const guide = request.runtime.context?.promptingGuide;
    if (!guide) return handler(request);
    return handler({
      ...request,
      systemMessage: request.systemMessage.concat(
        "\n\n# Agreed outline for this post\n\n" +
        "The orchestrator attached this outline. `call_editor_agent` hands it to the editor agent automatically, so don't copy it into the handoff. " +
        "When you review the draft, judge structure and groundedness against this outline.\n\n" +
        guide
      ),
    });
  },
});

export const editorManagerAgent = createAgent({
    model: editorManagerModel,
    tools: managerTools,
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
        applyToolConfig,
        showPromptingGuide,
        createVerifyEndRunMiddleware()
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: ManagerAgentState,
    contextSchema: ManagerAgentContext,
    checkpointer: checkpointer
});