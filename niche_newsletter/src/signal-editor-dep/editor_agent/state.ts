import { z } from "zod";
import { BaseMessage } from "@langchain/core/messages";
import { MessagesZodMeta } from "@langchain/langgraph";
import { registry } from "@langchain/langgraph/zod";

export const EditorAgentState = z.object({
  // MessagesZodMeta's optional fields aren't typed for exactOptionalPropertyTypes; cast is a library-typing gap, not a logic issue
  messages: z.array(z.custom<BaseMessage>()).default([]).register(registry, MessagesZodMeta as Parameters<typeof registry.add>[1]),
  researchTopic: z.string(),
  // Reducer appends: a tool returns just the new URL and LangGraph adds it to the list.
  chartUrl: z.array(z.string()).default([]).register(registry, {
    reducer: { schema: z.string(), fn: (urls: string[], url: string) => [...urls, url] },
    default: () => [],
  }),
  imageUrl: z.string().optional(),
});
export type AgentStateType = z.infer<typeof EditorAgentState>;