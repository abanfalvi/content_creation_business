import { z } from "zod";
import { BaseMessage } from "@langchain/core/messages";
import { MessagesZodMeta } from "@langchain/langgraph";
import { registry } from "@langchain/langgraph/zod";

export const OrchestratortState = z.object({
  // MessagesZodMeta's optional fields aren't typed for exactOptionalPropertyTypes; cast is a library-typing gap, not a logic issue
  messages: z.array(z.custom<BaseMessage>()).default([]).register(registry, MessagesZodMeta as Parameters<typeof registry.add>[1]),
});
export type AgentStateType = z.infer<typeof OrchestratortState>;

export const smPostRubric = z.object({
    formatCorrect: z.boolean().describe("Whether the post maintains consistency with the template post"),
    formatCorrectEvidence: z.string().describe("Explain why it maintains or does not maintain"),
});
export type SMPostRubricType = z.infer<typeof smPostRubric>;
