import { MODELS, opikHandler } from "../../models.js";
import { ResearchAgentState } from "./state.js"
import { researchTools } from "./tools.js"

import {
    createAgent,
    createMiddleware,
    modelFallbackMiddleware,
    toolRetryMiddleware,
    dynamicSystemPromptMiddleware,
    todoListMiddleware,
    countTokensApproximately,
    toolErrorMiddleware,
    type AnyAgentMiddleware,
    type ToolCallRequest
} from "langchain";
import { ChatOpenRouter } from "@langchain/openrouter";
import { readFile } from 'fs/promises';

import dotenv from 'dotenv';

dotenv.config();

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

function onRetry(error: unknown, request: ToolCallRequest): string | undefined {
    const toolName = request.toolCall.name;
    const err = error as Partial<NodeJS.ErrnoException> & { status?: number; statusCode?: number };

    // Node filesystem errors (readFile/writeFile/mkdir/appendFile) carry a `.code`
    if (err?.code) {
        switch (err.code) {
            case "ENOENT":
                return `Tool '${toolName}' failed: a required file was not found.`;
            case "EACCES":
            case "EPERM":
                return `Tool '${toolName}' failed: permission denied accessing the filesystem.`;
            case "ENOSPC":
                return `Tool '${toolName}' failed: no space left on disk.`;
            case "EMFILE":
                return `Tool '${toolName}' failed: too many open files.`;
            default:
                return `Tool '${toolName}' failed with a filesystem error (${err.code}).`;
        }
    }

    // HTTP-status-bearing errors from the search/LLM API clients (Tavily, OpenRouter)
    const status = err?.status ?? err?.statusCode;
    if (typeof status === "number") {
        if (status === 429) return `Tool '${toolName}' failed: rate limited, try again later.`;
        if (status === 401 || status === 403) return `Tool '${toolName}' failed: authentication error.`;
        if (status >= 500) return `Tool '${toolName}' failed: upstream service error (${status}).`;
        return `Tool '${toolName}' failed with HTTP status ${status}.`;
    }

    // Node's built-in fetch throws a TypeError for network-level failures (DNS, connection refused, etc.)
    if (error instanceof TypeError && "cause" in err) {
        return `Tool '${toolName}' failed: the network request could not be completed.`;
    }

    // A bare TypeError with no network `cause` is more likely an actual bug in the tool implementation
    if (error instanceof TypeError) {
        return `Tool '${toolName}' failed with TypeError.`;
    }
}

const researchModel = new ChatOpenRouter({
    model: MODELS.RESEARCH_AGENT,
    temperature: .2,
    maxTokens: 4096,
})

const SYSTEM_PROMPT = await readConfig("src/signal-editor-dep/research_agent/SYSTEM_PROMPT.md")

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
        request.state.probeCount >= 2;

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

const RESEARCH_TODO_DESCRIPTION = `Use this tool to plan and track the steps of your current research task.

Only use it when the research is non-trivial — several distinct leads to chase, a query broad enough to need breaking into sub-questions, or a task you expect to span many search rounds. For a quick, narrow lookup that resolves in a couple of searches, skip it and just do the work directly.

## When to use it
1. Breaking a broad research query into concrete sub-questions or angles to investigate separately.
2. Tracking which leads/sources you've already checked versus what's still open, so you don't repeat searches.
3. Planning follow-up steps that depend on what an earlier search turns up (e.g. "if X confirms this, check Y next").
4. Keeping track of what still needs a practical-application angle written up, versus what's just a raw fact so far.

## How to use it
1. Mark a step in_progress before starting it, and completed as soon as it's done — don't batch updates.
2. Revise the list as you go: drop steps that turn out irrelevant, add new ones a search surfaces (a new sub-topic, a source worth cross-checking).
3. Keep steps concrete and scoped to this research task ("check if Model X's release notes mention fine-tuning support") — not vague ("do more research").

## When NOT to use it
- A single, narrow question answerable in one or two searches.
- Purely reading back or editing your scratch pad notes — that's not a planning step.`;

// toolRetryMiddleware's internal Zod schema isn't typed for exactOptionalPropertyTypes; cast is a library-typing gap, not a logic issue
const searchRetryMiddleware = toolRetryMiddleware({
  tools: ["web_search"],
  maxRetries: 3,
  retryOn: (error) => error.name === "TimeoutError" || error.name === "NetworkError",
  backoffFactor: 1.5,
  initialDelayMs: 500,
  onFailure: "continue",
}) as AnyAgentMiddleware;


export const researchAgent = createAgent({
    model: researchModel,
    tools: researchTools,
    middleware: [
        compressGateMiddleware, 
        todoListMiddleware({ toolDescription: RESEARCH_TODO_DESCRIPTION }) as AnyAgentMiddleware,
        searchRetryMiddleware,
        toolErrorMiddleware({onError: onRetry})
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: ResearchAgentState,
})