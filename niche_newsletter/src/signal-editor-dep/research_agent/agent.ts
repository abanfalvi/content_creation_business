import { MODELS, opikHandler } from "../../models.js";
import { ResearchAgentState } from "./state.js";
import { researchTools, drainFinishedSubAgentTasks, getRunningSubAgentTasks } from "./tools.js";
import { onRetry } from "../../shared/on_error.js";
import { HumanMessage } from "@langchain/core/messages";

import {
    createAgent,
    createMiddleware,
    modelFallbackMiddleware,
    toolRetryMiddleware,
    modelRetryMiddleware,
    dynamicSystemPromptMiddleware,
    countTokensApproximately,
    toolErrorMiddleware,
    type AnyAgentMiddleware,
    type ToolCallRequest
} from "langchain";
import { ChatOpenRouter } from "@langchain/openrouter";
import { readFile } from 'fs/promises';

import dotenv from 'dotenv';

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const researchModel = new ChatOpenRouter({
    model: MODELS.RESEARCH_AGENT,
    temperature: .2,
    maxTokens: 4096,
    maxRetries: 2
})

const SYSTEM_PROMPT = await readConfig("src/signal-editor-dep/research_agent/SYSTEM_PROMPT.md")


const subAgentNotifyMiddleware = createMiddleware({
  name: "subAgentNotifyMiddleware",
  beforeModel: async () => {
    const finished = drainFinishedSubAgentTasks();
    if (finished.length === 0) return {};

    const summary = finished
      .map((t) =>
        t.status === "completed"
          ? `Subagent task ${t.taskId} finished:\n${t.result}`
          : `Subagent task ${t.taskId} failed: ${t.error}`
      )
      .join("\n\n---\n\n");

    return {
      messages: [
        new HumanMessage({
          content: `[Background subagent update]\n\n${summary}`,
          additional_kwargs: { lc_source: "subagent_notification" },
        }),
      ],
    };
  },
});

const checkUnfinishedSubAgents = createMiddleware({
  name: "checkUnfinishedSubagentMiddleware",

  afterAgent: {
    canJumpTo: ["model"],
    hook: async () => {
      const running = getRunningSubAgentTasks();
      if (running.length === 0) return undefined;

      const taskList = running.map((t) => `- ${t.taskId}`).join("\n");

      return {
        messages: [
          new HumanMessage({
            content: `[Subagent check] You still have ${running.length} spawn_subagent task(s) running and unaccounted for:\n${taskList}\n\nDo not end your turn while these are outstanding. Keep working on something else, or call check_subagent_status on them, before finishing.`,
            additional_kwargs: { lc_source: "subagent_notification" },
          }),
        ],
        jumpTo: "model",
      };
    },
  },
})

const compressGateMiddleware = createMiddleware({
  name: "compressGateMiddleware",
  stateSchema: ResearchAgentState.pick({ iterationCount: true, probeCount: true, summaryCount: true }),

  beforeModel: async (state) => { return { iterationCount: state.iterationCount + 1, probeCount: state.probeCount + 1 } },
  wrapModelCall: async (request, handler) => {
    const promptLength = countTokensApproximately(request.messages);
    const shouldExposeCompression =
        request.state.iterationCount >= 3 &&
        promptLength >= 40000 &&
        request.state.summaryCount < 1 &&
        request.state.probeCount >= 4;

    const tools = shouldExposeCompression
        ? request.tools
        : request.tools.filter((t) => t.name !== "compress_context");

    return handler({
      ...request,
      tools,
      ...(shouldExposeCompression ? { toolChoice: { type: "function" as const, function: { name: "compress_context" } } } : {}),
    });
  },
});

// toolRetryMiddleware's internal Zod schema isn't typed for exactOptionalPropertyTypes; cast is a library-typing gap, not a logic issue
const searchRetryMiddleware = toolRetryMiddleware({
  tools: ["web_search"],
  maxRetries: 3,
  retryOn: (error) => error.name === "TimeoutError" || error.name === "NetworkError",
  backoffFactor: 1.5,
  initialDelayMs: 500,
  onFailure: "continue",
}) as AnyAgentMiddleware;

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


export const researchAgent = createAgent({
    model: researchModel,
    tools: researchTools,
    middleware: [
        subAgentNotifyMiddleware,
        compressGateMiddleware,
        modelCallRetryMiddleware,
        searchRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
        checkUnfinishedSubAgents
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: ResearchAgentState,
})