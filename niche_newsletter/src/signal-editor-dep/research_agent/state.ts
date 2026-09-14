import { z } from "zod";
import { BaseMessage } from "@langchain/core/messages";
import { MessagesZodMeta } from "@langchain/langgraph";
import { registry } from "@langchain/langgraph/zod";

export const ResearchAgentState = z.object({
  // MessagesZodMeta's optional fields aren't typed for exactOptionalPropertyTypes; cast is a library-typing gap, not a logic issue
  messages: z.array(z.custom<BaseMessage>()).default([]).register(registry, MessagesZodMeta as Parameters<typeof registry.add>[1]),
  results: z.array(z.string()).default([]),
  researchTopic: z.string(),

  iterationCount: z.number().default(0), // total model-call iterations this run
  summaryCount: z.number().default(0), // how many times compress_context has actually compressed
  probeCount: z.number().default(0), // iterations since the compression gate last opened/reset
});
export type AgentStateType = z.infer<typeof ResearchAgentState>;

export const compressRubric= z.object({
    stuck: z.boolean().describe("if at least 3 of its last 4 search queries returned no new URLs or facts"),
    stuckEvidence: z.string().describe("if not stuck, quote at least one new URL or concrete fact obtained recently. Else explicitly name one distinct strategy it has not yet tried (e.g., a different search tool, query type, or angle)"),
    closedUnit: z.boolean().describe("if the trajectory has reached a clean stopping point"),
    closedUnitEvidence: z.string().describe("if closedUnit is true, quote the closing fragment of its last assistant message (showing a completed tool call or sub-analysis). Else quote the open fragment showing it is mid-thought"),
    summarizable: z.boolean().describe("verify if information can be compressed without data loss"),
    summarizableEvidence: z.string().describe("If summarizable is true, list 3-5 essential facts formatted with verbatim cited quotes; else explicitly name the class of information that would be lost"),
    progress: z.boolean().describe("confirm advancement since the last compaction"),
    progressEvidence: z.string().describe("If progress is true, cite the specific new concrete fact (name, date, URL, or claim) or refined sub-question; else state that the state is unchanged")
});
export type RubricType = z.infer<typeof compressRubric>;