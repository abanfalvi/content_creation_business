import { z } from "zod";
import { tool, type ToolRuntime } from "@langchain/core/tools";
import { createAgent } from "langchain";
import { join, basename } from 'path';
import { randomUUID } from 'node:crypto';
import { BaseMessage, getBufferString, HumanMessage, RemoveMessage, ToolMessage } from "@langchain/core/messages";
import type { RunnableConfig } from "@langchain/core/runnables";
import { Command, REMOVE_ALL_MESSAGES } from "@langchain/langgraph";
import { ChatOpenRouter } from "@langchain/openrouter";
import { MODELS, opikHandler } from "../../models.js";
import { ResearchAgentState, compressRubric } from "./state.js";
import type { RubricType } from "./state.js";
import { applyFindAndReplace, appendFileEnsuringDir, readOrInitFile, writeFileEnsuringDir } from "../../shared/file_utils.js";
import { dataPaths } from "../../shared/paths.js";
import { runWebSearch, webSearchSchema, extractWebContentTool, WEB_SEARCH_DESCRIPTION, type WebSearchInput } from "../../shared/parallel_web.js";
import { sharedSearchStore, researchContextSchema, recordSearch, recordAssignment, resolveContext, siblingSearchesMiddleware, type ResearchContext } from "./shared_search_memory.js";
import matter from "gray-matter";
import { glob } from "glob";

import dotenv from 'dotenv';
import { request } from "node:http";

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

const MIN_HISTORY_TO_COMPRESS = 6; // below this many older messages, compression isn't worth the summarization call

const compressionModel = new ChatOpenRouter(MODELS.MEMORY_MANAGEMENT_MODEL, { temperature: 0.2, callbacks: [opikHandler] });

const COMPRESSION_PROMPT = `You are compressing the working conversation history of a research agent gathering source material for a newsletter, so it can keep going without losing track of what's already been found or decided.

Read the conversation below and extract only what's needed to continue the work coherently. Structure your output with these sections, writing "None" where a section has nothing to report:

## RESEARCH BRIEF
What the agent was asked to research and why (topic, angle, intended use in the newsletter).

## FINDINGS SO FAR
Key facts, sources, or data points already gathered — with enough detail (source name/URL, key claim) that they don't need to be re-fetched.

## DISCARDED / IRRELEVANT LEADS
Sources or angles already checked and ruled out, so they aren't investigated again.

## OPEN QUESTIONS
What's still unresolved or needs further digging.

## NEXT STEPS
What remains to finish this research task.

Respond ONLY with the filled-in sections above — no preamble, no text before or after.

Conversation to compress:
{messages}`;

async function summarizeMessages(messagesToSummarize: BaseMessage[], config?: RunnableConfig): Promise<string> {
  const formatted = getBufferString(messagesToSummarize);
  const response = await compressionModel.invoke(COMPRESSION_PROMPT.replace("{messages}", formatted), config);
  return typeof response.content === "string" ? response.content : JSON.stringify(response.content);
}

const webSearchTool = tool(
  async (input: WebSearchInput, runtime: ToolRuntime<any, ResearchContext>) => {
    const results = await runWebSearch(input);
    await recordSearch(runtime.store, runtime.context, input.queries.join(" | "), { results });
    return JSON.stringify(results);
  },
  {
    name: "web_search",
    description: WEB_SEARCH_DESCRIPTION,
    schema: webSearchSchema,
  }
);

const compressContext = tool(
  async (rubric: RubricType, runtime: ToolRuntime<typeof ResearchAgentState>) => {
    const shouldCompress = rubric.stuck && rubric.closedUnit && rubric.summarizable && rubric.progress;

    if (!shouldCompress) {
      return new Command({
        update: {
          messages: [new ToolMessage({ content: "Compression was not triggered — not every rubric condition was met yet.", tool_call_id: runtime.toolCallId })],
          probeCount: 0,
        },
      });
    }

    const messages = [...(runtime.state.messages ?? [])];

    const currentCall = messages[messages.length - 1]!;
    const history = messages.slice(0, -1);

    if (history.length < MIN_HISTORY_TO_COMPRESS) {
      return new Command({
        update: {
          messages: [new ToolMessage({ content: "Not enough conversation history yet to make compression worthwhile.", tool_call_id: runtime.toolCallId })],
          probeCount: 0,
        },
      });
    }

    const summary = await summarizeMessages(history, runtime.config);
    const summaryMessage = new HumanMessage({
      content: `Here is a summary of the conversation so far, replacing the earlier messages that were compressed:\n\n${summary}`,
      additional_kwargs: { lc_source: "summarization" },
    });

    return new Command({
      update: {
        messages: [
          new RemoveMessage({ id: REMOVE_ALL_MESSAGES }),
          summaryMessage,
          currentCall,
          new ToolMessage({
            content: `Context compressed: ${history.length} message(s) condensed into the summary above.`,
            tool_call_id: runtime.toolCallId,
          }),
        ],
        probeCount: 0,
        summaryCount: runtime.state.summaryCount + 1,
      },
    });
  },
  {
    name: "compress_context",
    description:
      "Report your self-assessment of the conversation against the rubric (stuck, closedUnit, summarizable, progress, each with evidence). If every condition holds, your conversation history is compressed automatically into a structured summary (research brief, findings so far, discarded leads, open questions, next steps), replacing all prior messages. If any condition doesn't hold, nothing is compressed — you'll get back which conditions weren't met. Only offered to you when the middleware judges it's worth considering; call it with your honest assessment whenever it's available.",
    schema: compressRubric,
  }
);

const readScratchPad = tool(
    async (_input, runtime: ToolRuntime<typeof ResearchAgentState>) => {
        const researchTopic = runtime.state.researchTopic;
        const path = dataPaths.researchScratchPad();
        const fullPath = join(path, `${researchTopic}_notes.md`);
        return await readOrInitFile(fullPath);
    }, {
        name: "read_scratchpad",
        description: "Read the current notes from your research findings"
    }
)

const editScratchPad = tool(
  async ({ to_replace, replace_with }, runtime: ToolRuntime<typeof ResearchAgentState>) => {
    const researchTopic = runtime.state.researchTopic;
    const path = dataPaths.researchScratchPad();
    const fullPath = join(path, `${researchTopic}_notes.md`);

    const outcome = await applyFindAndReplace(fullPath, to_replace, replace_with);
    if (outcome.status === "not_found") {
        return `"${to_replace}" not found in file (checked exact and whitespace-flexible matches).`;
    }
    if (outcome.status === "ambiguous") {
        return `"${to_replace}" found ${outcome.count} times — expected exactly one match, aborting edit.`;
    }

    return outcome.result;
  }, {
    name: "edit_scratchpad",
    description: "Edit the content of your notes about the research findings",
    schema: z.object({
        to_replace: z.string().describe("Content to replace"),
        replace_with: z.string().describe("Content to replace with")
    })
  }
);

const addContent = tool(
  async ({ content }, runtime: ToolRuntime<typeof ResearchAgentState>) => {
    const researchTopic = runtime.state.researchTopic;
    const path = dataPaths.researchScratchPad();
    const fullPath = join(path, `${researchTopic}_notes.md`);
    await appendFileEnsuringDir(fullPath, content);

    return "Your notes have been added";
  }, {
    name: "add_content_to_scratch_pad",
    description: "Add your notes to the scratch pad",
    schema: z.object({
        content: z.string().describe("Content to add"),
    })
  }
);

const TODO_STATUS = z.enum(["pending", "in_progress", "completed"]);

const TodoSchema = z.object({
  content: z.string().describe("A concrete, scoped research step, e.g. \"check if Model X's release notes mention fine-tuning support\" — not vague like \"do more research\"."),
  status: TODO_STATUS.describe("Current status of this step."),
});

const WRITE_TODOS_DESCRIPTION = `Use this tool to plan and track the steps of your current research task.

Only use it when the research is non-trivial — several distinct leads to chase, a query broad enough to need breaking into sub-questions, or a task you expect to span many search rounds. For a quick, narrow lookup that resolves in a couple of searches, skip it and just do the work directly.

This tool REPLACES the entire todo list with what you pass in — always include every step (not just the ones that changed), or earlier steps will be lost. Read the list first with read_todos if you're not sure what's already on it.

## When to use it
1. Breaking a broad research query into concrete sub-questions or angles to investigate separately.
2. Tracking which leads/sources you've already checked versus what's still open, so you don't repeat searches.
3. Planning follow-up steps that depend on what an earlier search turns up (e.g. "if X confirms this, check Y next").
4. Keeping track of what still needs a practical-application angle written up, versus what's just a raw fact so far.

## How to use it
1. Mark a step in_progress before starting it, and completed as soon as it's done — don't batch updates.
2. Revise the list as you go: drop steps that turn out irrelevant, add new ones a search surfaces (a new sub-topic, a source worth cross-checking).
3. Keep steps concrete and scoped to this research task — not vague.

## When NOT to use it
- A single, narrow question answerable in one or two searches.
- Purely reading back or editing your scratch pad notes — that's not a planning step.`;

const readTodos = tool(
  async () => {
    const path = dataPaths.researchScratchPad();
    const fullPath = join(path, "todos.json");
    return await readOrInitFile(fullPath, "[]");
  }, {
    name: "read_todos",
    description: "Read your current research todo list.",
  }
);

const writeTodos = tool(
  async ({ todos }) => {
    const path = dataPaths.researchScratchPad();
    const fullPath = join(path, "todos.json");
    await writeFileEnsuringDir(fullPath, JSON.stringify(todos, null, 2));

    return `Updated todo list to ${JSON.stringify(todos)}`;
  }, {
    name: "write_todos",
    description: WRITE_TODOS_DESCRIPTION,
    schema: z.object({
      todos: z.array(TodoSchema).describe("The full todo list — this replaces whatever was there before, so include every step, not just the changed ones."),
    }),
  }
);

const skimPreviousFindings = tool(
  async () => {
    const prevNotes = await glob("**/*_notes.md", { cwd: dataPaths.researchScratchPad(), absolute: true });
    const contents: Record<string, any> = {};
    for (const note of prevNotes) {
      const topicName = basename(note, "_notes.md");
      const raw = await readOrInitFile(note);
      const parsed = matter(raw);
      contents[topicName] = parsed.data
    }
    return contents
  }, {
    name: "skim_previous_findings",
    description: "Get the title and descriptions of the previous notes to decide if there any relevant that can be used."
  });

const readPreviousFinding = tool(
  async ({notesTopic, sameTopic}, runtime: ToolRuntime) => {
    const topic = notesTopic.toLowerCase().replace(/[^a-z0-9]+/g, "_")
    const fullPath = join(dataPaths.researchScratchPad(), `${topic}_notes.md`);
    let content: string;
    try {
        content = await readOrInitFile(fullPath);
      } catch {
        return "File not found, please use the topic names returned in the skimPreviousFindings tool"
      }
    if (!sameTopic) {
      return content
    } else {
      return new Command({
        update: {
          messages: [
            new ToolMessage({content: content, tool_call_id: runtime.toolCallId})
          ],
          // researchTopic: topic
        }
      })
    }
  }, {
    name: "read_previous_finding",
    description: "Read the content of the previous research finding",
    schema: z.object({
      notesTopic: z.string().describe("name of the topic that is relevant"),
      sameTopic: z.boolean().describe("Whether the current research topic is the same as an already previously made research topic")
    })
  }
);


interface SubAgentTask {
  /** The research run (context.researchRunId) that spawned it — parallel runs share this process. */
  runId: string;
  status: "running" | "completed" | "failed";
  result?: string;
  error?: string;
  /** Whether the parent agent has already been shown this task's result. */
  delivered?: boolean;
  /** Settles when the subagent finishes either way, so the parent can wait on it. */
  done: Promise<void>;
}

// Module-scoped, in-memory only — tasks don't survive a process restart and
// aren't part of graph state. Every lookup is scoped by research run, so parallel
// research agents in the same process never see (or wait on) each other's tasks.
const subAgentTasks = new Map<string, SubAgentTask>();

type FinishedTask = { taskId: string; status: "completed" | "failed"; result?: string; error?: string };

/**
 * Pulls this run's finished (completed/failed) tasks the parent agent hasn't seen yet,
 * marking them delivered so they're only surfaced once, then forgets them.
 */
export function drainFinishedSubAgentTasks(runId: string): FinishedTask[] {
  const finished: FinishedTask[] = [];
  for (const [taskId, task] of subAgentTasks) {
    if (task.runId !== runId || task.delivered || task.status === "running") continue;
    task.delivered = true;
    finished.push({
      taskId,
      status: task.status,
      ...(task.result !== undefined && { result: task.result }),
      ...(task.error !== undefined && { error: task.error }),
    });
  }
  return finished;
}

/** Read-only peek at this run's tasks that are still running. */
export function getRunningSubAgentTasks(runId: string): string[] {
  return [...subAgentTasks].filter(([, t]) => t.runId === runId && t.status === "running").map(([id]) => id);
}

/**
 * Waits until all of this run's running tasks have finished, or `timeoutMs` passes.
 * Returns true if everything finished in time.
 */
export async function waitForSubAgentTasks(runId: string, timeoutMs: number): Promise<boolean> {
  const pending = [...subAgentTasks.values()].filter((t) => t.runId === runId && t.status === "running").map((t) => t.done);
  if (pending.length === 0) return true;
  let timer: NodeJS.Timeout | undefined;
  const timedOut = new Promise<false>((resolve) => { timer = setTimeout(() => resolve(false), timeoutMs); });
  try {
    return await Promise.race([Promise.all(pending).then(() => true as const), timedOut]);
  } finally {
    clearTimeout(timer);
  }
}

/** Formats finished tasks as the message the parent agent sees. */
export function formatFinishedSubAgentTasks(finished: FinishedTask[]): string {
  return finished
    .map((t) => t.status === "completed"
      ? `Subagent task ${t.taskId} finished:\n${t.result}`
      : `Subagent task ${t.taskId} failed: ${t.error}`)
    .join("\n\n---\n\n");
}

const subAgentModel = new ChatOpenRouter({ model: MODELS.RESEARCH_AGENT, temperature: 0.2, maxTokens: 4096, maxRetries: 2 });

const SUBAGENT_SYSTEM_PROMPT = "You are a focused research subagent. A parent research agent has given you one specific question or sub-task — investigate it thoroughly using web search, then return a concise, well-sourced write-up (what you found, why it matters, sources). Don't ask for clarification — do the best job you can with the instruction given. Your response is the only thing the parent agent sees, so make it self-contained.";

const researchSubAgent = createAgent({
  model: subAgentModel,
  tools: [webSearchTool, extractWebContentTool],
  systemPrompt: SUBAGENT_SYSTEM_PROMPT,
  middleware: [siblingSearchesMiddleware],
  contextSchema: researchContextSchema,
  store: sharedSearchStore,
});

const spawnSubAgent = tool(
  async ({ instruction }, runtime: ToolRuntime<any, ResearchContext>) => {
    const taskId = randomUUID();
    const subAgentId = `sub-${taskId.slice(0, 8)}`;
    const { researchRunId } = resolveContext(runtime.context);
    // Recorded under the subagent's id so the parent and siblings see the angle as claimed.
    await recordAssignment(runtime.store, { agentId: subAgentId, researchRunId }, instruction);

    const task: SubAgentTask = { runId: researchRunId, status: "running", done: Promise.resolve() };
    subAgentTasks.set(taskId, task);
    task.done = researchSubAgent
      .invoke(
        { messages: [new HumanMessage(instruction)] },
        { callbacks: [opikHandler], recursionLimit: 200, context: { agentId: subAgentId, researchRunId } },
      )
      .then((result) => {
        const messages = result.messages as BaseMessage[];
        const last = messages[messages.length - 1];
        const content = typeof last?.content === "string" ? last.content : JSON.stringify(last?.content ?? "");
        task.status = "completed";
        task.result = content;
      })
      .catch((error) => {
        task.status = "failed";
        task.error = String(error);
      });

    return `Spawned subagent. Task ID: ${taskId}. It runs in the background — keep working on other angles and check back with check_subagent_status when you're ready for the result, not immediately.`;
  },
  {
    name: "spawn_subagent",
    description: "Delegate a specific, self-contained research question to an isolated subagent that investigates it independently using web search, without adding its search noise to your own context. Runs in the background and returns a task ID immediately, not the result. Launch several in one turn (multiple tool calls) to investigate independent angles in parallel. Only the subagent's final write-up comes back to you, never its intermediate searches.",
    schema: z.object({
      instruction: z.string().describe("A specific, self-contained research question or task. The subagent sees only this instruction and nothing else about your conversation, so include everything it needs to know."),
    }),
  }
);

const checkSubAgentStatus = tool(
  async ({ taskId }, runtime: ToolRuntime<any, ResearchContext>) => {
    const task = subAgentTasks.get(taskId);
    if (!task || task.runId !== resolveContext(runtime.context).researchRunId) return `No subagent task found for ID '${taskId}'.`;
    if (task.status !== "running") task.delivered = true;
    if (task.status === "running") return `Task ${taskId} is still running.`;
    if (task.status === "failed") return `Task ${taskId} failed: ${task.error}`;
    return task.result;
  },
  {
    name: "check_subagent_status",
    description: "Check on a subagent task started with spawn_subagent. Returns its result once finished, its error if it failed, or confirmation it's still running.",
    schema: z.object({
      taskId: z.string().describe("The exact task ID returned by spawn_subagent. Pass it verbatim."),
    }),
  }
);

export const researchTools = [webSearchTool, compressContext, readScratchPad, editScratchPad, addContent, readTodos, writeTodos, extractWebContentTool, skimPreviousFindings, readPreviousFinding, spawnSubAgent, checkSubAgentStatus];