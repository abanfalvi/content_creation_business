// Summarise the transcript -> create the skill -> regression tests execute -> approved/rejected

import { onRetry } from "../../../src/shared/on_error.js";
import { z } from "zod";
import {
    createAgent,
    toolCallLimitMiddleware,
    modelRetryMiddleware,
    toolErrorMiddleware,
    type AnyAgentMiddleware,
} from "langchain";
import { ChatOpenRouter } from "@langchain/openrouter";
import { END, START, StateGraph, type ConditionalEdgeRouter, type GraphNode } from "@langchain/langgraph";
import { ToolMessage } from "@langchain/core/messages";
import { readFile } from 'fs/promises';
import { join } from "node:path";

import { MODELS } from "../../../src/models.js";
import { createFilesystemMiddleware, FilesystemBackend } from "deepagents";
import { skillOptimizerState } from "./state.js";
import { runRegression } from "./regression_tests.js";
import fs from "node:fs";
import { Opik, TestSuite } from "opik";
import { skillEvalSuiteName, type SkillEvalItemData } from "../trace_schema.js";
import { isSkillEvalData } from "./utils.js";
import matter from "gray-matter";
import { glob } from "glob";

const MAX_ATTEMPTS = 3;
// Working copy of src/skills the optimizer edits and the regression run reads (via SKILLS_ROOT).
// The caller fills it before the run; it only reaches src/skills through save_skills, after the gate approves.
export const TMP_SKILLS_DIR = "self_evolution/skill_evolution/skill_optimizer/tmp_skills";
const LIVE_SKILLS_DIR = "src/skills";
// dotenv.config(); // loaded via --import dotenv/config in bin/niche_newsletter.js

async function readConfig(path: string): Promise<string> {
  const content = await readFile(path, 'utf-8');
  return content;
}

const SYSTEM_PROMPT = await readConfig("self_evolution/skill_evolution/skill_optimizer/SYSTEM_PROMPT.md");
const SUM_SESSION_PROMPT = await readConfig("self_evolution/skill_evolution/skill_optimizer/SUM_SESSION_PROMPT.md");
const TEST_INPUT_REFINER_PROMPT = await readConfig("self_evolution/skill_evolution/skill_optimizer/TEST_INPUT_REFINER_PROMPT.md");

const skillOptimizerModel = new ChatOpenRouter({
    model: MODELS.SKILL_OPTIMIZER_MODEL,
    temperature: .3,
    maxTokens: 8192,
    maxRetries: 2,
})

const traceSummariserModel = new ChatOpenRouter({
    model: MODELS.TRACE_SUMMARIZER_MODEL,
    temperature: .3,
    maxTokens: 4096,
    maxRetries: 2,
})

const testInputRefinerModel = new ChatOpenRouter({
    model: MODELS.TRACE_SUMMARIZER_MODEL,
    temperature: .3,
    maxTokens: 2048,
    maxRetries: 2,
})

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

const deleteLimitMiddleware = toolCallLimitMiddleware({
  toolName: "delete",
  runLimit: 2,
  exitBehavior: "continue",
} as never) as AnyAgentMiddleware;

const skillFilesBackend = new FilesystemBackend({rootDir: TMP_SKILLS_DIR, virtualMode: true});

export const skillOptimizerAgent = createAgent({
    model: skillOptimizerModel,
    tools: [],
    middleware: [
        modelCallRetryMiddleware,
        toolErrorMiddleware({onError: onRetry}),
        createFilesystemMiddleware({
            backend: skillFilesBackend,
            tools: ["ls", "read_file", "edit_file", "write_file", "glob", "grep", "delete"],
        }),
        deleteLimitMiddleware
    ],
    systemPrompt: SYSTEM_PROMPT,
    // checkpointer: checkpointer
});

/** Removes everything inside the directory but keeps the directory. */
export function emptyDir(dir: string): void {
    fs.rmSync(dir, { recursive: true, force: true });
    fs.mkdirSync(dir, { recursive: true });
}

const traceSummarisation: GraphNode<typeof skillOptimizerState> = async (state) => {

    const result = await traceSummariserModel.invoke([{
        role: "system",
        content: SUM_SESSION_PROMPT,
    }, {
        role: "user",
        content: state.traceTranscript.text
    }]);

    return {traceSummary: result.content as string}
};

const adjustTestSuiteCases: GraphNode<typeof skillOptimizerState> = async (state) => {
    const client = new Opik({ projectName: "niche_newsletter" });
    const suite = await TestSuite.get(client, skillEvalSuiteName(state.agentName), "niche_newsletter");
    const suiteItems = await suite.getItems();
    const files = await glob("**/*.md", { cwd: "self_evolution/skill_evolution/skill_optimizer/tmp_skills" });
    const skills = (await Promise.all(files.map(async (file: string) => {
        try {
            const { data, content } = matter(await readFile(join("self_evolution/skill_evolution/skill_optimizer/tmp_skills", file), "utf-8"));
            return {
                name: String(data.name),
                description: String(data.description)
            }
        }
        catch (error) {
            console.warn(`[skill reader] skipped ${file}: ${String(error)}`);
            return undefined;
        }
    }))).filter((m): m is NonNullable<typeof m> => m !== undefined);

    for (const [i, item] of suiteItems.entries()) {
        if (!isSkillEvalData(item.data)) continue;
        // Refine from the real message, not from an earlier refinement, so a rerun gives the same result and doesn't shrink it further.
        const originalInput = item.data.replay.originalInput ?? item.data.replay.input;
        const result = await testInputRefinerModel.invoke([{
            role: "system",
            content: TEST_INPUT_REFINER_PROMPT,
        }, {
            role: "user",
            content: `User question that triggered the run: ${originalInput}\n\nThe steps the agent took to solve the problem:\n${item.data.transcript}\n\nThe agent's current skills:\n ${skills.map((skill) => `- ${skill.name}: ${skill.description}`)}`
        }]);

        const newInput = typeof result?.content === "string" ? result.content : JSON.stringify(result?.content ?? "")

        await suite.update([
            {id: item.id, data: {...item.data, replay: { ...item.data.replay, originalInput, input: newInput }}}
        ]);
    }

    return {}
}

const skillCreation: GraphNode<typeof skillOptimizerState> = async (state) => {

    // On a retry the previous attempt's regression failures are what the optimizer has to fix.
    const feedback = state.regressionReport
        ? `\n\n# Regression test failures from your previous attempt\n${state.regressionReport}`
        : "";
    const result = await skillOptimizerAgent.invoke({
        // The prompt expects the agent's name on the first line; the trace summary doesn't reliably include it.
        messages: [{ role: "human", content: `Agent to improve: ${state.agentName}\n\n${state.traceSummary}${feedback}` }]
    });

    const last = result.messages.at(-1);

    return {
        optimizerActions: typeof last?.content === "string" ? last.content : JSON.stringify(last?.content ?? ""),
        history: `skill_creation attempt ${state.history.length + 1}`,
    }
};

const regressionTest: GraphNode<typeof skillOptimizerState> = async (state) => {
    const result = await runRegression(state.agentName);
    // A run that could not finish says nothing about the skill; retrying skill_creation would not help.
    if (result.error) throw new Error(result.report);
    return { regressionPass: result.passed, regressionReport: result.report };
};

const saveCreateSkill: GraphNode<typeof skillOptimizerState> = async (state) => {
    const source = join(TMP_SKILLS_DIR, state.agentName);
    const dest = join(LIVE_SKILLS_DIR, state.agentName);

    fs.rmSync(dest, { recursive: true, force: true });
    if (fs.existsSync(source)) fs.cpSync(source, dest, { recursive: true });
    else fs.mkdirSync(dest, { recursive: true });

    emptyDir(TMP_SKILLS_DIR);
    return {}
}

const routeAfterRegression: ConditionalEdgeRouter<typeof skillOptimizerState> = (state) => {
  if (state.regressionPass) {
    return "save_skills";
  }

  if (state.history.length >= MAX_ATTEMPTS) {
    return END;
  }

  return "skill_creation";
};


export const skillOptimizerWorkflow = new StateGraph(skillOptimizerState)
    .addNode("trace_summariser", traceSummarisation)
    .addNode("skill_creation", skillCreation)
    .addNode("test_input_refining", adjustTestSuiteCases)
    .addNode("regression_test", regressionTest)
    .addNode("save_skills", saveCreateSkill)
    .addEdge(START, "trace_summariser")
    .addEdge("trace_summariser", "skill_creation")
    .addEdge("skill_creation", "test_input_refining")
    .addEdge("test_input_refining", "regression_test")
    .addConditionalEdges(
        "regression_test",
        routeAfterRegression,
        ["save_skills", "skill_creation", END],
    )
    .addEdge("save_skills", END)
    .compile();

// await graph.invoke({messages: "agentTraces"})