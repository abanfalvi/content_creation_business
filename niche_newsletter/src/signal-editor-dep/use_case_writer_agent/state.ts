import { z } from "zod";
import { BaseMessage } from "@langchain/core/messages";
import { MessagesZodMeta } from "@langchain/langgraph";
import { registry } from "@langchain/langgraph/zod";

export const UseCaseWriterAgentState = z.object({
  // MessagesZodMeta's optional fields aren't typed for exactOptionalPropertyTypes; cast is a library-typing gap, not a logic issue
  messages: z.array(z.custom<BaseMessage>()).default([]).register(registry, MessagesZodMeta as Parameters<typeof registry.add>[1]),
  researchTopic: z.string()
});
export type AgentStateType = z.infer<typeof UseCaseWriterAgentState>;