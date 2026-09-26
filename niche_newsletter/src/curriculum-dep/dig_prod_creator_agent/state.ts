import { z } from "zod";
import { BaseMessage } from "@langchain/core/messages";
import { MessagesZodMeta } from "@langchain/langgraph";
import { registry } from "@langchain/langgraph/zod";
import { type ClientTool } from "@langchain/core/tools";

const generatedImage = z.object({
  imageUrl: z.string(),
  prompt: z.string(),
});

export const DigProdCreationAgentState = z.object({
  messages: z.array(z.custom<BaseMessage>()).default([]).register(registry, MessagesZodMeta as Parameters<typeof registry.add>[1]),
  doc_content_path: z.string(),
  useCanva: z.boolean().default(false),
  images: z.record(z.string(), generatedImage).default({}),
  documents: z.record(z.string(), z.string()).default({}),
  sandboxId: z.string().optional(),
  pendingDocumentUrl: z.string().optional()
});
export type AgentStateType = z.infer<typeof DigProdCreationAgentState>;