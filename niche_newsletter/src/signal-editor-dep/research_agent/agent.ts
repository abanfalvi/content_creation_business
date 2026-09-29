import { MODELS, opikHandler } from "../../models.js";
import { ResearchAgentState } from "./state.js";
import { researchTools, drainFinishedSubAgentTasks, getRunningSubAgentTasks, waitForSubAgentTasks, formatFinishedSubAgentTasks } from "./tools.js";
import { onRetry } from "../../shared/on_error.js";
import { HumanMessage } from "@langchain/core/messages";
import { sharedSearchStore, researchContextSchema, resolveContext, siblingSearchesMiddleware } from "./shared_search_memory.js";
import { z } from "zod";

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
import { checkpointer } from "../checkpointer.js";

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
  contextSchema: researchContextSchema,
  beforeModel: async (_state, runtime) => {
    const finished = drainFinishedSubAgentTasks(resolveContext(runtime.context).researchRunId);
    if (finished.length === 0) return {};

    return {
      messages: [
        new HumanMessage({
          content: `[Background subagent update]\n\n${formatFinishedSubAgentTasks(finished)}`,
          additional_kwargs: { lc_source: "subagent_notification" },
        }),
      ],
    };
  },
});

// How long the parent waits for its subagents once it has nothing else to do, and how
// many times it may be sent back to work before it's allowed to finish regardless.
const SUBAGENT_WAIT_MS = 5 * 60 * 1000;
const MAX_SUBAGENT_WAIT_ROUNDS = 3;

// When the parent tries to finish while its subagents are still running, wait for them
// here (instead of bouncing the model straight back, which made it loop "waiting…" as
// fast as it could answer until the provider errored), then hand it their results once.
const checkUnfinishedSubAgents = createMiddleware({
  name: "checkUnfinishedSubagentMiddleware",
  contextSchema: researchContextSchema,
  stateSchema: z.object({ subAgentWaitRounds: z.number().default(0) }),

  afterAgent: {
    canJumpTo: ["model"],
    hook: async (state, runtime) => {
      const { researchRunId } = resolveContext(runtime.context);
      if (getRunningSubAgentTasks(researchRunId).length === 0 && state.subAgentWaitRounds === 0) {
        // Nothing outstanding — but results that finished after the last model call
        // still need to reach the parent before it ends.
        const finished = drainFinishedSubAgentTasks(researchRunId);
        if (finished.length === 0) return undefined;
        return backToModel(state.subAgentWaitRounds, `[Background subagent update]\n\n${formatFinishedSubAgentTasks(finished)}\n\nIncorporate these results before finishing.`);
      }
      if (state.subAgentWaitRounds >= MAX_SUBAGENT_WAIT_ROUNDS) return undefined;

      const allDone = await waitForSubAgentTasks(researchRunId, SUBAGENT_WAIT_MS);
      const finished = drainFinishedSubAgentTasks(researchRunId);
      const stillRunning = getRunningSubAgentTasks(researchRunId);
      if (finished.length === 0 && stillRunning.length === 0) return undefined;

      const parts = [];
      if (finished.length > 0) parts.push(`[Background subagent update]\n\n${formatFinishedSubAgentTasks(finished)}`);
      if (!allDone && stillRunning.length > 0) {
        parts.push(`[Subagent check] ${stillRunning.length} subagent task(s) are still running after waiting ${SUBAGENT_WAIT_MS / 60000} minutes:\n${stillRunning.map((id) => `- ${id}`).join("\n")}\nFinish with what you have if they aren't essential.`);
      }
      parts.push("Incorporate these results before finishing.");
      return backToModel(state.subAgentWaitRounds, parts.join("\n\n"));
    },
  },
});

function backToModel(rounds: number, content: string) {
  return {
    subAgentWaitRounds: rounds + 1,
    messages: [new HumanMessage({ content, additional_kwargs: { lc_source: "subagent_notification" } })],
    jumpTo: "model" as const,
  };
}

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
        siblingSearchesMiddleware,
        compressGateMiddleware,
        modelCallRetryMiddleware,
        searchRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
        checkUnfinishedSubAgents
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: ResearchAgentState,
    contextSchema: researchContextSchema,
    store: sharedSearchStore,
    checkpointer: checkpointer
})