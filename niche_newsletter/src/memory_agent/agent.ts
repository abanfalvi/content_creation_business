import { onRetry } from "../shared/on_error.js";

import {
    createAgent,
    toolCallLimitMiddleware,
    modelFallbackMiddleware,
    applyStrategy,
    detectEmail,
    createMiddleware,
    modelRetryMiddleware,
    toolErrorMiddleware,
    type AnyAgentMiddleware,
} from "langchain";
import { CompositeBackend, createFilesystemMiddleware, createSkillsMiddleware, FilesystemBackend } from "deepagents";
import { skillsBackend } from "../shared/skills.js";
import { ChatOpenRouter } from "@langchain/openrouter";
import { ToolMessage } from "@langchain/core/messages";
import { readFile } from 'fs/promises';

import dotenv from 'dotenv';
import { MODELS } from "../models.js";
import { MemoryManageAgentState } from "./state.js";
import { memoryManageAgentTools } from "./tools.js";
import { dataPaths } from "../shared/paths.js";

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const memoryManageModel = new ChatOpenRouter({
    model: MODELS.MEMORY_MANAGEMENT_MODEL,
    temperature: .3,
    maxTokens: 4096,
    maxRetries: 2
})

const SYSTEM_PROMPT = await readConfig("src/memory_agent/SYSTEM_PROMPT.md")

const modelCallRetryMiddleware = modelRetryMiddleware({
  maxRetries: 3,
  retryOn: (error) =>
    error.message === "terminated" ||
    error.name === "TimeoutError" ||
    error.name === "NetworkError" ||
    error instanceof TypeError,
  backoffFactor: 1.5,
  initialDelayMs: 1000,
  onFailure: "continue",
}) as AnyAgentMiddleware;

// The memories tree stays the default; skills are mounted beside it, as in the orchestrator.
const memoryBackend = new CompositeBackend(
    new FilesystemBackend({rootDir: dataPaths.memories(), virtualMode: true}),
    {"/skills/": skillsBackend("memory_agent")},
);

export const memoryManageAgent = createAgent({
    model: memoryManageModel,
    tools: memoryManageAgentTools,
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
        createFilesystemMiddleware({
            backend: memoryBackend,
            tools: ["ls", "read_file", "edit_file", "write_file", "glob", "grep"],
        }),
        createSkillsMiddleware({ backend: memoryBackend, sources: ["/skills/"] }),
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: MemoryManageAgentState,
});