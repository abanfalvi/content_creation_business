// Live shared memory between the research agent and its subagents within one run.
// Every web search (and every subagent assignment) is written to a shared store;
// before each model call, the Jev decisions model scores whether the agent is duplicating what the
// *other* agents have covered, and only then shows it those entries so it changes direction.

import { z } from "zod";
import { randomUUID } from "node:crypto";
import { InMemoryStore, type BaseStore } from "@langchain/langgraph";
import { createMiddleware } from "langchain";
import { HumanMessage } from "@langchain/core/messages";
import { OpenRouter } from "@openrouter/sdk";
import type { DecisionsNoulQuestion, DecisionsRequest } from "@openrouter/sdk/models";
import { MODELS } from "../../models.js";

export const sharedSearchStore = new InMemoryStore();

export const researchContextSchema = z.object({
  agentId: z.string().default("parent"),
  researchRunId: z.string().default("default"),
});
export type ResearchContext = z.infer<typeof researchContextSchema>;

export function newResearchRunId(): string {
  return randomUUID();
}

const namespace = (runId: string) => ["research_run", runId, "searches"];

const MAX_DIGEST_ENTRIES = 30;
const MAX_LINE_CHARS = 200;

interface SearchEntry {
  agentId: string;
  kind: "search" | "assignment";
  text: string;
  /** Monotonic write order; Date.now() can tie within a millisecond and hide entries from the watermark. */
  seq: number;
}

let nextSeq = 0;

export function resolveContext(context: Partial<ResearchContext> | undefined): ResearchContext {
  return {
    agentId: context?.agentId ?? "parent",
    researchRunId: context?.researchRunId ?? "default",
  };
}

function summarizeSearchResults(query: string, rawResults: unknown): string {
  const results = (rawResults as { results?: { title?: string; url?: string }[] })?.results ?? [];
  const top = results.slice(0, 3).map((r) => r.title ?? r.url).filter(Boolean).join(" | ");
  const line = top ? `"${query}" → ${top}` : `"${query}" → no results`;
  return line.slice(0, MAX_LINE_CHARS);
}

// ToolRuntime types its store as core's generic BaseStore; at runtime it is the langgraph store passed to createAgent.
type MaybeStore = unknown;

async function putEntry(store: MaybeStore, context: Partial<ResearchContext> | undefined, kind: SearchEntry["kind"], text: string) {
  if (!store) return;
  const graphStore = store as BaseStore;
  const { agentId, researchRunId } = resolveContext(context);
  const entry: SearchEntry = { agentId, kind, text: text.slice(0, MAX_LINE_CHARS), seq: nextSeq++ };
  await graphStore.put(namespace(researchRunId), randomUUID(), entry);
}

export async function recordSearch(store: MaybeStore, context: Partial<ResearchContext> | undefined, query: string, rawResults: unknown) {
  await putEntry(store, context, "search", summarizeSearchResults(query, rawResults));
}

export async function recordAssignment(store: MaybeStore, context: Partial<ResearchContext> | undefined, instruction: string) {
  await putEntry(store, context, "assignment", instruction);
}

// Overlap judge: before each model call, Jev scores whether
// this agent's recent direction duplicates what the other agents have already covered. The
// agent is only steered when the score crosses the threshold, and a second Jev question then
// narrows what it is shown to just the entries it duplicates; otherwise nothing is injected.
const decisionsClient = new OpenRouter({ apiKey: process.env.OPENROUTER_API_KEY ?? "" });

const MAX_OWN_ENTRIES = 8;
/** Jev's noul score is 0..1; at or above this the agent is considered to be duplicating others. */
const OVERLAP_THRESHOLD = 0.5;

type DecisionsQuestions = DecisionsRequest["questions"];

const OVERLAP_QUESTION = {
  overlapping: {
    type: "noul",
    instructions:
      "Parallel research agents are working on the same newsletter research run. Is THIS agent dangerously heading in the same direction as work the other agents have already covered, so that its next searches would mostly re-find the same sources, facts, or angle? Different sub-topics, source types, or angles on the same broad topic are NOT overlap; only clear duplication of effort is.",
    criteria: {
      true: "Its assignment or recent searches clearly duplicate entries the other agents already covered.",
      false: "It is exploring a meaningfully different sub-question, source type, or angle.",
    },
  },
} satisfies DecisionsQuestions;

function formatEntry(e: SearchEntry): string {
  return e.kind === "assignment" ? `[${e.agentId}] assigned: ${e.text}` : `[${e.agentId}] searched ${e.text}`;
}

/** Asks Jev the given noul questions in one request; returns each 0..1 score, or undefined when the check couldn't be made. */
async function askJev(questions: DecisionsQuestions, own: SearchEntry[], others: SearchEntry[], sessionId: string): Promise<Record<string, number> | undefined> {
  try {
    const response = await decisionsClient.alpha.decisions.create({
      decisionsRequest: {
        model: MODELS.OVERLAP_JUDGE_MODEL,
        questions,
        state: {
          thisAgentRecentDirection: own.map(formatEntry),
          alreadyCoveredByOtherAgents: others.map(formatEntry),
        },
        sessionId,
      },
    });
    const scores: Record<string, number> = {};
    for (const [key, answer] of Object.entries(response.answers)) {
      if (answer?.type === "noul") scores[key] = (answer as { noul: number }).noul;
    }
    return scores;
  } catch (error) {
    // Fail open: a judge failure never blocks or steers the agent.
    console.warn(`[overlap judge] skipped: ${String(error)}`);
    return undefined;
  }
}

/** First Jev question: is this agent duplicating the others' work at all? */
async function scoreOverlap(own: SearchEntry[], others: SearchEntry[], sessionId: string): Promise<number | undefined> {
  return (await askJev(OVERLAP_QUESTION, own, others, sessionId))?.["overlapping"];
}

/**
 * Second Jev question, only asked once overlap is confirmed: one noul question per covered
 * entry (batched in a single request), so the agent is shown only the entries it duplicates.
 * Falls back to every covered entry if the filter fails or flags none.
 */
async function filterOverlapping(own: SearchEntry[], others: SearchEntry[], sessionId: string): Promise<SearchEntry[]> {
  const questions: DecisionsQuestions = Object.fromEntries(
    others.map((e, i) => {
      const question: DecisionsNoulQuestion = {
        type: "noul",
        instructions: `Does THIS agent's recent direction duplicate this specific entry already covered by another agent: ${formatEntry(e)}? Only answer yes if continuing would probably re-find the same sources, facts, or angle as this entry.`,
        criteria: {
          true: "This agent is probably re-covering this entry's query, sources, or angle.",
          false: "This entry is about a different sub-question, source type, or angle than this agent.",
        },
      };
      return [`entry_${i}`, question];
    })
  );
  const scores = await askJev(questions, own, others, sessionId);
  if (!scores) return others;
  const flagged = others.filter((_e, i) => (scores[`entry_${i}`] ?? 0) >= OVERLAP_THRESHOLD);
  return flagged.length > 0 ? flagged : others;
}

// Highest store seq each agent was last judged against, so the judge only runs when
// something new was written (by this agent or its siblings) since the previous check.
const lastJudgedSeq = new Map<string, number>();

export const siblingSearchesMiddleware = createMiddleware({
  name: "siblingSearchesMiddleware",
  contextSchema: researchContextSchema,
  beforeModel: async (_state, runtime) => {
    const store = runtime.store as BaseStore | undefined;
    if (!store) return {};
    const { agentId, researchRunId } = resolveContext(runtime.context);

    const entries = (await store.search(namespace(researchRunId), { limit: 500 }))
      .map((i) => i.value as unknown as SearchEntry)
      .sort((a, b) => a.seq - b.seq);

    const own = entries.filter((e) => e.agentId === agentId).slice(-MAX_OWN_ENTRIES);
    const others = entries.filter((e) => e.agentId !== agentId).slice(-MAX_DIGEST_ENTRIES);
    if (own.length === 0 || others.length === 0) return {};

    const judgeKey = `${researchRunId}:${agentId}`;
    const latestSeq = entries[entries.length - 1]!.seq;
    if ((lastJudgedSeq.get(judgeKey) ?? -1) >= latestSeq) return {};
    lastJudgedSeq.set(judgeKey, latestSeq);

    const score = await scoreOverlap(own, others, researchRunId);
    if (score === undefined || score < OVERLAP_THRESHOLD) return {};

    const overlapping = await filterOverlapping(own, others, researchRunId);

    return {
      messages: [
        new HumanMessage({
          content: `[Shared research memory] You're heading into ground other agents in this run have already covered. Already covered:\n${overlapping.map((e) => `- ${formatEntry(e)}`).join("\n")}\n\nChange direction: pick a different sub-question, source type, or angle instead of repeating these.`,
          additional_kwargs: { lc_source: "sibling_digest" },
        }),
      ],
    };
  },
});
