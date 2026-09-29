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
import { CompositeBackend, createFilesystemMiddleware, FilesystemBackend, StateBackend } from "deepagents";
import { dataPaths } from "../shared/paths.js";
import { type DecisionsRequest } from "@openrouter/sdk/models";
import { OpenRouter } from "@openrouter/sdk";
import { readOrInitFile } from "../shared/file_utils.js";

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const orchestratorModel = new ChatOpenRouter({
    model: MODELS.MAIN_ORCHESTRATOR_MODEL,
    temperature: .2,
    maxTokens: 8196,
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
});

const decisionsClient = new OpenRouter({ apiKey: process.env.OPENROUTER_API_KEY ?? "" });
type DecisionsQuestions = DecisionsRequest["questions"];

const INPUT_THEME_QUESTION = {
  themeChoice: {
    type: "choice",
    instructions:
      "Which content strategy theme is the most closely related to the user's question?",
    criteria: {
      promptEngeering: "The user wants to work on, create posts on prompting techniques.",
      LLMEval: "The user wants to work on, create posts on LLM evaluation techniques.",
      AutomationTechniques: "The user wants to work on, create posts on AI automation techniques.",
      Other: "The user wants to work on, create posts on any other topics, does not belong to any other theme"
    },
  },
} satisfies DecisionsQuestions;

const THEME_FILES: Record<string, string> = {
  promptEngeering: "content_strategy/prompt_engineering.md",
  LLMEval: "content_strategy/llm_evaluation_techniques.md",
  AutomationTechniques: "content_strategy/automation_strategies.md",
};

const contentStrategyMiddleware = createMiddleware({
  name: "ContentStrategy",
  stateSchema: z.object({ contentStrategy: z.string().default("") }),

  beforeAgent: async (state) => {
    const lastHuman = [...state.messages].reverse().find((m) => HumanMessage.isInstance(m));
    if (!lastHuman) return { contentStrategy: "" };
    try {
      const response = await decisionsClient.alpha.decisions.create({
        decisionsRequest: {
          model: MODELS.OVERLAP_JUDGE_MODEL,
          questions: INPUT_THEME_QUESTION,
          state: { userQuestion: lastHuman.text },
        },
      });
      const answer = response.answers.themeChoice;
      const choiceMade = answer?.type === "choice" ? answer.choice : undefined;
      const file = choiceMade ? THEME_FILES[choiceMade] : undefined;
      return { contentStrategy: file ? await readOrInitFile(file) : "" };
    } catch (error) {
      console.warn(`[content strategy selector] skipped: ${String(error)}`);
      return { contentStrategy: "" };
    }
  },

  wrapModelCall: (request, handler) => {
    const { contentStrategy } = request.state;
    if (!contentStrategy) return handler(request);
    return handler({
      ...request,
      systemPrompt: `${request.systemMessage}\n\n# Relevant content strategy theme\n\n${contentStrategy}`,
    });
  },
});


export const orchestratorAgent = createAgent({
    model: orchestratorModel,
    tools: orchestratorTools,
    middleware: [
        // memoryPhaseMiddleware,
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
        createFilesystemMiddleware({
            backend: new CompositeBackend(
                new FilesystemBackend({rootDir: dataPaths.contentStrategy(), virtualMode: true}),
                { "/large_tool_results/": new StateBackend() },
            ),
            tools: ["ls", "read_file", "edit_file", "write_file", "glob", "grep"],
        }),
        modelFallbackMiddleware(
          new ChatOpenRouter({ model: MODELS.ORCHESTRATOR_FALLBACK_1, temperature: .2, maxTokens: 8196, maxRetries: 2 }),
          new ChatOpenRouter({ model: MODELS.ORCHESTRATOR_FALLBACK_2, temperature: .2, maxTokens: 8196, maxRetries: 2 }),
        ),
        contentStrategyMiddleware,
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: OrchestratortState,
    checkpointer: checkpointer
});