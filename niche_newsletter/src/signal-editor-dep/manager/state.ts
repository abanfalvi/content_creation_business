import { z } from "zod";
import { BaseMessage } from "@langchain/core/messages";
import { MessagesZodMeta } from "@langchain/langgraph";
import { registry } from "@langchain/langgraph/zod";

export const ManagerAgentState = z.object({
  // MessagesZodMeta's optional fields aren't typed for exactOptionalPropertyTypes; cast is a library-typing gap, not a logic issue
  messages: z.array(z.custom<BaseMessage>()).default([]).register(registry, MessagesZodMeta as Parameters<typeof registry.add>[1]),
  researchTopic: z.string(),
  currentStep: z.string()
});
export type AgentStateType = z.infer<typeof ManagerAgentState>;

export const newsletterRubric = z.object({
    structure: z.number().min(0).max(2).describe("0: a wall of undifferentiated text, or no clear headline/section breakdown. 1: has sections, but they don't clearly mirror the research findings and use cases the editor was given. 2: a clear headline and a section structure that mirrors the supplied findings/use cases, with every section earning its place"),
    structureEvidence: z.string().describe("Quote the headline and list the section headers found, or point to where the structure is missing/unclear"),

    visualRelevance: z.number().min(0).max(2).describe("0: visuals are decorative or forced into sections that didn't need one, or a section with a real stat/comparison/trend has no chart. 1: mixed — some visuals earn their place, others don't. 2: every chart or image adds information a reader needs (charts next to real data claims, images next to concepts that need a picture), and no section that needed one is missing it"),
    visualRelevanceEvidence: z.string().describe("For each visual in the draft, name its section and whether it's backed by data/a concept that needed it; if there are no visuals, confirm none of the sections needed one"),

    groundedness: z.number().min(0).max(2).describe("0: contains at least one claim not traceable to the supplied research findings/use cases. 1: mostly grounded, but something reads as invented or embellished beyond the source material. 2: every claim in the draft is traceable back to the research/use-case material the editor was given"),
    groundednessEvidence: z.string().describe("Quote any claim that isn't traceable to the source material, or confirm none were found"),

    formatCorrect: z.boolean().describe("Whether the draft was actually saved in beehiiv using the documented post format/metadata (per learn_post_authoring/learn_post_metadata), not a guessed format. False is disqualifying on its own, regardless of the other scores, since a malformed draft won't render for the human reviewer"),
    formatCorrectEvidence: z.string().describe("Quote the specific format/metadata problem found, or confirm the saved post matches the documented format"),
});
export type NewsletterRubricType = z.infer<typeof newsletterRubric>;