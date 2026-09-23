import { HumanMessage, type BaseMessage } from "@langchain/core/messages";
import { INTERRUPT, isInterrupted } from "@langchain/langgraph";
import { readFile } from "node:fs/promises";
import { sideEffectLog, type SideEffect } from "../../src/shared/eval_guard.js";
import { contentToText } from "../../src/tui/message_format.js";
import type { AgentName, EvalProblem } from "../problems/types.js";
import {
    CLEAN_NOTES, LEAD_MAGNET_STRATEGY, NOTES_WITH_UNVERIFIED_CLAIM, RAW_NOTES_WITH_PLANTED_FLAWS, USE_CASES,
    notesPath, resetDataDirs, strategyPath, useCasesPath, writeFixture,
} from "./fixtures.js";

type Invokable = { invoke(input: unknown, config?: unknown): Promise<Record<string, unknown>> };

// Dynamic imports, so agent modules (and their MCP loaders) only load after the runner
// has set EVAL_MODE, and only for the suites actually being run.
const AGENTS: Record<AgentName, () => Promise<Invokable>> = {
    research_agent: async () => (await import("../../src/signal-editor-dep/research_agent/agent.js")).researchAgent as unknown as Invokable,
    rel_filter_agent: async () => (await import("../../src/signal-editor-dep/rel_filter_agent/agent.js")).relFilterAgent as unknown as Invokable,
    use_case_writer_agent: async () => (await import("../../src/signal-editor-dep/use_case_writer_agent/agent.js")).userCaseWriterAgent as unknown as Invokable,
    editor_agent: async () => (await import("../../src/signal-editor-dep/editor_agent/agent.js")).editorAgent as unknown as Invokable,
    sm_agent: async () => (await import("../../src/distribution-dep/sm_agent/agent.js")).SMAgent as unknown as Invokable,
    dig_prod_creator_agent: async () => (await import("../../src/curriculum-dep/dig_prod_creator_agent/agent.js")).DigProdCreationAgent as unknown as Invokable,
    system: async () => (await import("../../src/orchestrator/orchestrator.js")).orchestratorAgent as unknown as Invokable,
};

const TIMEOUT_MS = { standard: 10 * 60_000, expensive: 40 * 60_000 };
const RECURSION_LIMIT = 80;
const SECTION_LIMIT = 20_000;

export type RunOutput = {
    output: string;
    tool_calls: string[];
    interrupted: boolean;
    error: string | null;
};

// All cases in a run share one DATA_ROOT (checkpointers bind to it at import), and each
// case resets its data directories, so cases run one at a time even if the eval engine
// schedules them concurrently.
let queue: Promise<unknown> = Promise.resolve();
function runExclusive<T>(fn: () => Promise<T>): Promise<T> {
    const next = queue.then(fn, fn);
    queue = next.catch(() => undefined);
    return next;
}

export function runProblem(problem: EvalProblem, runId: string): Promise<RunOutput> {
    return runExclusive(() => runProblemNow(problem, runId));
}

async function runProblemNow(problem: EvalProblem, runId: string): Promise<RunOutput> {
    const topic = `eval_${problem.case_id}`;
    const effectsStart = sideEffectLog.length;
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(new Error(`timed out after ${TIMEOUT_MS[problem.cost] / 60_000} min`)), TIMEOUT_MS[problem.cost]);

    try {
        await resetDataDirs();
        await seedFixture(problem, topic);
        const agent = await AGENTS[problem.agent]();
        const result = await agent.invoke(buildInput(problem, topic), {
            configurable: { thread_id: `eval:${runId}:${problem.case_id}` },
            recursionLimit: RECURSION_LIMIT,
            signal: abort.signal,
        });
        const artifact = await readArtifact(problem, topic, result);
        return summarize(problem, result, artifact, sideEffectLog.slice(effectsStart), null);
    } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        return summarize(problem, { messages: [] }, null, sideEffectLog.slice(effectsStart), message);
    } finally {
        clearTimeout(timer);
    }
}

async function seedFixture(problem: EvalProblem, topic: string): Promise<void> {
    switch (problem.fixture) {
        case "raw_notes": return writeFixture(notesPath(topic), RAW_NOTES_WITH_PLANTED_FLAWS);
        case "clean_notes": return writeFixture(notesPath(topic), CLEAN_NOTES);
        case "unverified_notes": return writeFixture(notesPath(topic), NOTES_WITH_UNVERIFIED_CLAIM);
        case "notes_and_use_cases":
            await writeFixture(notesPath(topic), CLEAN_NOTES);
            return writeFixture(useCasesPath(topic), USE_CASES);
        case "lead_magnet_strategy": return writeFixture(strategyPath(topic), LEAD_MAGNET_STRATEGY);
        case undefined: return;
    }
}

function buildInput(problem: EvalProblem, topic: string): Record<string, unknown> {
    if (problem.agent === "system") {
        return { messages: [new HumanMessage(problem.message ?? "")] };
    }
    const messages = [new HumanMessage({ content: JSON.stringify(problem.handoff) })];
    switch (problem.agent) {
        case "sm_agent": return { messages };
        case "dig_prod_creator_agent": return { messages, doc_content_path: strategyPath(topic) };
        default: return { messages, researchTopic: topic };
    }
}

async function readArtifact(problem: EvalProblem, topic: string, result: Record<string, unknown>): Promise<{ label: string; content: string } | null> {
    const read = (path: string) => readFile(path, "utf-8").catch(() => "(file was not created)");
    switch (problem.agent) {
        case "research_agent":
        case "rel_filter_agent":
            return { label: "Final research notes file", content: await read(notesPath(topic)) };
        case "use_case_writer_agent":
            return { label: "Final how-to file", content: await read(useCasesPath(topic)) };
        case "dig_prod_creator_agent": {
            const code = lastToolArgs(messagesOf(result), "create_document")?.code;
            return { label: "Last create_document script", content: typeof code === "string" ? code : "(create_document was never called)" };
        }
        default:
            return null;
    }
}

function messagesOf(result: Record<string, unknown>): BaseMessage[] {
    return (result.messages ?? []) as BaseMessage[];
}

type ToolCall = { name: string; args: Record<string, unknown> };

function toolCallsOf(messages: BaseMessage[]): ToolCall[] {
    return messages.flatMap((message) =>
        message.getType() === "ai" ? ((message as unknown as { tool_calls?: ToolCall[] }).tool_calls ?? []) : [],
    );
}

function lastToolArgs(messages: BaseMessage[], name: string): Record<string, unknown> | undefined {
    return toolCallsOf(messages).filter((call) => call.name === name).at(-1)?.args;
}

const clip = (text: string, limit = SECTION_LIMIT) => (text.length > limit ? `${text.slice(0, limit)}\n…(truncated)` : text);

function summarize(
    problem: EvalProblem,
    result: Record<string, unknown>,
    artifact: { label: string; content: string } | null,
    effects: SideEffect[],
    error: string | null,
): RunOutput {
    const messages = messagesOf(result);
    const calls = toolCallsOf(messages);
    const interrupted = error === null && isInterrupted(result);
    const pending = interrupted ? (result as Record<string | symbol, unknown[]>)[INTERRUPT]?.[0] : undefined;
    const finalAi = [...messages].reverse().find((message) => message.getType() === "ai");

    const sections = [
        `## Final message from the agent\n${finalAi ? clip(contentToText(finalAi.content)) || "(empty)" : "(none)"}`,
        artifact ? `## ${artifact.label}\n${clip(artifact.content)}` : null,
        error
            ? "## Tool calls made by the agent, in order\n(unknown: the run threw before returning its state, so its tool calls could not be read)"
            : `## Tool calls made by the agent, in order\n${calls.map((call, i) => `${i + 1}. ${call.name}(${clip(JSON.stringify(call.args), 600)})`).join("\n") || "(none)"}`,
        `## Write calls intercepted by the eval guard (recorded, never sent)\n${effects.map((e) => `- ${e.server}.${e.tool}(${clip(JSON.stringify(e.args), 4000)})`).join("\n") || "(none)"}`,
        problem.expects_interrupt || interrupted
            ? `## Human-review gate\n${interrupted ? `Paused for review. Pending action:\n${clip(JSON.stringify((pending as { value?: unknown })?.value, null, 2), 8000)}` : "The run did not pause at the review gate."}`
            : null,
        error ? `## Run error\n${error}` : null,
    ];

    return {
        output: sections.filter((section): section is string => section !== null).join("\n\n"),
        tool_calls: calls.map((call) => call.name),
        interrupted,
        error,
    };
}
