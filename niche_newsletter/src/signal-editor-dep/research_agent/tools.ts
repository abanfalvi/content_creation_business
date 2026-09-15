import { string, z } from "zod";
import { tool, type ToolRuntime } from "@langchain/core/tools";
import { TavilySearch } from "@langchain/tavily";
import { join } from 'path';
import { BaseMessage, getBufferString, HumanMessage, RemoveMessage, ToolMessage } from "@langchain/core/messages";
import type { RunnableConfig } from "@langchain/core/runnables";
import { Command, REMOVE_ALL_MESSAGES } from "@langchain/langgraph";
import { ChatOpenRouter } from "@langchain/openrouter";
import { MODELS, opikHandler } from "../../models.js";
import { ResearchAgentState, compressRubric } from "./state.js";
import type { RubricType } from "./state.js";
import { applyFindAndReplace, appendFileEnsuringDir, readOrInitFile, writeFileEnsuringDir } from "../../shared/file_utils.js";

import dotenv from 'dotenv';

dotenv.config();

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
  async ({ query, maxResults, includeDomains }) => {
    const searchTool = new TavilySearch({
      maxResults: maxResults,
      searchDepth: "basic",
      includeDomains: includeDomains,
      // ...(includeRawContent ? { includeRawContent } : {}),
    });
    // TavilySearch's schema is built on zod/v3, which TS can't cross-check cleanly against this file's zod v4 imports;
    // the object shape below is correct per TavilySearch's own documented usage.
    const results = await searchTool.invoke({ query } as unknown as Parameters<typeof searchTool.invoke>[0]);
    return JSON.stringify(results);
  },
  {
    name: "web_search",
    description: "Search the web for information relevant to the query.",
    schema: z.object({
      query: z.string().describe("the search query"),
      maxResults: z.number().optional().default(5).describe("max number of results to return"),
      includeDomains: z.array(z.string()).optional().default([]).describe("List of domains/sites to include in the search results"),
      // searchDepth: z.enum(["basic", "advanced"]).default("basic").describe("depth of search, advanced costs more, but gives more thorough results"),
      // includeRawContent: z.enum(["markdown", "text"]).optional().describe("Set this to also get each result's full cleaned page content (not just a short excerpt). Costs more latency and tokens — only ask for it when the default excerpt isn't enough to confirm a finding or write up its practical application.")
    }),
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
        const path = "src/signal-editor-dep/research_agent/scratch_pad/";
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
    const path = "src/signal-editor-dep/research_agent/scratch_pad/";
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
    const path = "src/signal-editor-dep/research_agent/scratch_pad/";
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
    const path = "src/signal-editor-dep/research_agent/scratch_pad/";
    const fullPath = join(path, "todos.json");
    return await readOrInitFile(fullPath, "[]");
  }, {
    name: "read_todos",
    description: "Read your current research todo list.",
  }
);

const writeTodos = tool(
  async ({ todos }) => {
    const path = "src/signal-editor-dep/research_agent/scratch_pad/";
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

export const researchTools = [webSearchTool, compressContext, readScratchPad, editScratchPad, addContent, readTodos, writeTodos];