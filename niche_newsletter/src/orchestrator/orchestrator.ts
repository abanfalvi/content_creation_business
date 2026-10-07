import { onRetry } from "../shared/on_error.js";
import { z } from "zod";
import {
    createAgent,
    toolCallLimitMiddleware,
    modelFallbackMiddleware,
    applyStrategy,
    detectEmail,
    createMiddleware,
    modelRetryMiddleware,
    piiMiddleware,
    toolErrorMiddleware,
    toolRetryMiddleware,
    type AnyAgentMiddleware,
} from "langchain";
import { ChatOpenRouter } from "@langchain/openrouter";
import { AIMessage, HumanMessage, ToolMessage } from "@langchain/core/messages";
import { readFile } from 'fs/promises';
import { basename, join } from "node:path";

import dotenv from 'dotenv';
import { MODELS } from "../models.js";
import { OrchestratortState, type AgentStateType } from "./state.js";
import { orchestratorTools } from "./tools.js";
import { checkpointer } from "./checkpointer.js";
import { CompositeBackend, createFilesystemMiddleware, createSkillsMiddleware, FilesystemBackend, StateBackend } from "deepagents";
import { dataPaths } from "../shared/paths.js";
import { type DecisionsRequest } from "@openrouter/sdk/models";
import { OpenRouter } from "@openrouter/sdk";
import { readOrInitFile } from "../shared/file_utils.js";
import { glob } from "glob";
import matter from "gray-matter";
import { memo } from "react";

// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const orchestratorModel = new ChatOpenRouter({
    model: MODELS.MAIN_ORCHESTRATOR_MODEL,
    temperature: .2,
    maxTokens: 15000,
    maxRetries: 2,
    provider: {
      sort: "price"
    }
})

if (!process.env.BEEHIIV_PUBLICATION_ID) {
    throw new Error("BEEHIIV_PUBLICATION_ID is not set — add it to .env (find it with beehiiv's list_publications).");
}
const SYSTEM_PROMPT = (await readConfig("src/orchestrator/SYSTEM_PROMPT.md"))
    .replaceAll("{{BEEHIIV_PUBLICATION_ID}}", process.env.BEEHIIV_PUBLICATION_ID);

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

const decisionsClient = new OpenRouter({ apiKey: process.env.OPENROUTER_API_KEY ?? "" });
type DecisionsQuestions = DecisionsRequest["questions"];

const INPUT_THEME_QUESTION = {
  themeChoice: {
    type: "choice",
    instructions:
      "Which content strategy theme is the most closely related to the user's question?",
    criteria: {
      promptEngeering: "The user wants to work on, create posts on prompting techniques.",
      LLMEval: "The user wants to work on, create posts on LLM evaluation techniques.",
      automationTechniques: "The user wants to work on, create posts on AI automation techniques.",
      Other: "The user wants to work on, create posts on any other topics, does not belong to any other theme"
    },
  },
} satisfies DecisionsQuestions;

const THEME_FILES: Record<string, string> = {
  promptEngeering: join(dataPaths.contentStrategy(), "prompt_engineering.md"),
  LLMEval: join(dataPaths.contentStrategy(), "llm_evaluation_techniques.md"),
  automationTechniques: join(dataPaths.contentStrategy(), "automation_strategies.md"),
};

const contentStrategyMiddleware = createMiddleware({
  name: "ContentStrategy",
  stateSchema: z.object({ contentStrategy: z.string().default("") }),

  beforeAgent: async (state) => {
    const lastHuman = [...state.messages].reverse().find((m) => HumanMessage.isInstance(m));
    if (!lastHuman) return { contentStrategy: "" };
    try {
      const response = await decisionsClient.alpha.decisions.create({
        decisionsRequest: {
          model: MODELS.OVERLAP_JUDGE_MODEL,
          questions: INPUT_THEME_QUESTION,
          state: { userQuestion: lastHuman.text },
        },
      });
      const answer = response.answers.themeChoice;
      const choiceMade = answer?.type === "choice" ? answer.choice : undefined;
      const file = choiceMade ? THEME_FILES[choiceMade] : undefined;
      return { contentStrategy: file ? await readOrInitFile(file) : "" };
    } catch (error) {
      console.warn(`[content strategy selector] skipped: ${String(error)}`);
      return { contentStrategy: "" };
    }
  },

  wrapModelCall: (request, handler) => {
    const { contentStrategy } = request.state;
    if (!contentStrategy) return handler(request);
    return handler({
      ...request,
      systemMessage: request.systemMessage.concat(
        `\n\n# Relevant content strategy theme\n\n${contentStrategy}`
      ),
    });
  },
});

const retrieveMemoryMiddleware = createMiddleware({
  name: "retrieve_memory_middleware",
  stateSchema: z.object({ relevantMemory: z.string().default("") }),

  beforeAgent: async (state) => {
    const lastHuman = [...state.messages].reverse().find((m) => HumanMessage.isInstance(m));
    if (!lastHuman) return { relevantMemory: "" };
    const files = await glob("**/*.md", { cwd: dataPaths.memories() });
    if (files.length == 0) return { relevantMemory: "" }
    const memories = (await Promise.all(files.map(async (file) => {
      try {
          const { data, content } = matter(await readFile(join(dataPaths.memories(), file), "utf-8"));
          return { 
            name: String(data.name ?? basename(file)),
            description: String(data.description ?? ""),
            content
          };
      } catch (error) {
        console.warn(`[relevant memory snippet selector] skipped ${file}: ${String(error)}`);
        return undefined;
     }
    }))).filter((m): m is NonNullable<typeof m> => m !== undefined);
    if (memories.length === 0) return { relevantMemory: "" };

    const MEMORY_CHOICES = {
      memoryChoice: {
        type: "choice",
        instructions:
          "Which of the saved memory contents could provide valuable context to the agent?",
        criteria: {
          none: "None of the saved memories can provide relevant context for the agent",
          ...Object.fromEntries(
            memories.map(({name, description}) => [ name, description ])
          )
        },
      },
    } satisfies DecisionsQuestions;
    try {
      const response = await decisionsClient.alpha.decisions.create({
        decisionsRequest: {
          model: MODELS.OVERLAP_JUDGE_MODEL,
          questions: MEMORY_CHOICES,
          state: { userQuestion: lastHuman.text },
        },
      });
      const answer = response.answers.memoryChoice;
      const choiceMade = answer?.type === "choice" ? answer.choice : undefined;
      const picked = memories.find((m) => m.name === choiceMade);
      return { relevantMemory: picked?.content ?? "" };
    } catch (error) {
      console.warn(`[relevant memory snippet selector] skipped: ${String(error)}`);
      return { relevantMemory: "" };
    }
  },

  wrapModelCall: (request, handler) => {
    const { relevantMemory } = request.state;
    if (!relevantMemory) return handler(request);
    return handler({
      ...request,
      systemMessage: request.systemMessage.concat(
        `\n\n# Relevant information retrieved from memory\n\n${relevantMemory}`
      ),
    });
  },

});


// Management notes (content_strategy/, content_plans/, ...) at the root; the orchestrator's skills (read by the skills middleware
// and opened by the model via read_file) under /skills/.
const orchestratorBackend = new CompositeBackend(
    new FilesystemBackend({rootDir: dataPaths.managementNotes(), virtualMode: true}),
    {
        "/large_tool_results/": new StateBackend(),
        "/skills/": new FilesystemBackend({rootDir: "src/orchestrator/skills", virtualMode: true}),
    },
);

export const orchestratorAgent = createAgent({
    model: orchestratorModel,
    tools: orchestratorTools,
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
        createFilesystemMiddleware({
            backend: orchestratorBackend,
            tools: ["ls", "read_file", "edit_file", "write_file", "glob", "grep"],
        }),
        createSkillsMiddleware({ backend: orchestratorBackend, sources: ["/skills/"] }),
        modelFallbackMiddleware(
          new ChatOpenRouter({ model: MODELS.ORCHESTRATOR_FALLBACK_1, temperature: .2, maxTokens: 8196, maxRetries: 2 }),
          new ChatOpenRouter({ model: MODELS.ORCHESTRATOR_FALLBACK_2, temperature: .2, maxTokens: 8196, maxRetries: 2 }),
        ),
        contentStrategyMiddleware,
        retrieveMemoryMiddleware
    ],
    systemPrompt: SYSTEM_PROMPT,
    stateSchema: OrchestratortState,
    checkpointer: checkpointer
});