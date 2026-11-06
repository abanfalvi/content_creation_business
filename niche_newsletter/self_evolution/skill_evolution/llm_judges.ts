import { TestSuite, Opik } from 'opik';
import { ChatOpenRouter } from '@langchain/openrouter';
import { z } from 'zod';
import type { Transcript } from './trace_transcript.js';
import { buildSkillEvalItem, hasCase, skillEvalSuiteName, type SkillEvalItemData } from './trace_schema.js';

const client = new Opik();

const PROJECT_NAME = "niche_newsletter";
// Opik's built-in judges (GEval etc.) only accept OpenAI/Anthropic/Google model IDs, so the judge runs through OpenRouter.
const JUDGE_MODEL = "z-ai/glm-5.3-flash";
const JUDGE_ATTEMPTS = 2;

export interface JudgeRubric {
    taskIntroduction: string;
    evaluationCriteria: string;
}

const DEFAULT_RUBRIC: JudgeRubric = {
    taskIntroduction:
        "You are an expert judge reviewing the step-by-step transcript of an AI agent working on a task. " +
        "Each step shows what the agent said, which tools it called with which arguments, and what the tools returned.",
    evaluationCriteria:
        "Score how well the agent completed the task it was given. Penalise: tool calls that failed and were repeated or ignored, " +
        "skill or instruction files that were read but not followed, claims in the final answer that the tool results do not support, " +
        "steps that were skipped, and wasted or circular work. Reward a direct path to a correct, complete result.",
};

const scoreSchema = z.object({
    reasoning: z.string().describe("What went well and what went wrong, citing step numbers"),
    score: z.number().int().min(1).max(5).describe("1 = failed or badly flawed, 3 = acceptable with notable problems, 5 = excellent"),
});
const assertionsSchema = z.object({ assertions: z.array(z.string()).min(1).max(5) });

type Reply<T> = { raw: { content: unknown; response_metadata?: Record<string, unknown> }; parsed: T | null | undefined };

/** Calls the OpenRouter judge with structured output, retrying when it answers in prose instead of calling the tool. */
async function askJudge<T>(schema: z.ZodType<T>, system: string, user: string): Promise<T> {
    const model = new ChatOpenRouter({ model: JUDGE_MODEL, temperature: 0.4, maxTokens: 8000, maxRetries: 2 })
        .withStructuredOutput(schema, { method: "functionCalling", includeRaw: true }) as { invoke(input: unknown): Promise<unknown> };
    let last: Reply<T> | undefined;
    for (let attempt = 0; attempt < JUDGE_ATTEMPTS; attempt++) {
        last = (await model.invoke([{ role: "system", content: system }, { role: "user", content: user }])) as Reply<T>;
        if (last.parsed) return last.parsed;
    }
    const finish = last?.raw.response_metadata?.finish_reason ?? "unknown";
    throw new Error(`Judge ${JUDGE_MODEL} returned no structured reply after ${JUDGE_ATTEMPTS} attempts (finish_reason: ${finish})`);
}

/** Normalised to 0-1 so it stays comparable to a threshold: 1->0, 3->0.5, 5->1. */
async function judgeTranscript(rubric: JudgeRubric, agent: string, transcript: Transcript) {
    const system = `${rubric.taskIntroduction}

        ${rubric.evaluationCriteria}

        Give an integer score from 1 to 5 and the reasoning behind it.`;
            const user = `# Agent
        ${agent}

        # Task given to the agent
        ${transcript.input}

        # Steps
        ${transcript.text}`;
    const { score, reasoning } = await askJudge(scoreSchema, system, user);
    return { name: "agent_trajectory_quality", value: (score - 1) / 4, reason: reasoning };
}

export interface AgentEvalOptions {
    /** Which checkpoint DB the transcript came from. */
    department?: SkillEvalItemData["source"]["department"];
    /** Per-agent rubric; defaults to a general agent-trajectory rubric. */
    rubric?: JudgeRubric;
    /** Scores below this go into the suite. */
    threshold?: number;
    /** Suite size at which the skill self-evolution run is due. */
    minCases?: number;
    opikTraceId?: string;
    /** Called once the suite holds at least `minCases` items. Fires on every low-score run past that point until the cases are consumed. */
    onReady?: (info: { agent: string; suiteName: string; count: number }) => Promise<void> | void;
}

export interface AgentEvalResult {
    score: number;
    reason: string | undefined;
    /** True when this run's transcript was added to the suite. */
    inserted: boolean;
    /** Suite size after this run; undefined when the suite was not touched. */
    count: number | undefined;
    readyForEvolution: boolean;
}

/** Turns the judge's critique into checkable statements, so the re-run is judged on the specific failure and not on a generic "good output". */
async function deriveAssertions(agent: string, transcript: Transcript, reason: string): Promise<string[]> {
    const fallback = [`The agent does not repeat this problem: ${reason}`];
    try {
        const { assertions } = await askJudge(
            assertionsSchema,
            [
                "You write test assertions for an AI agent. Write 1-5 assertions that a reviewer could check against a FUTURE run of the same kind of task to confirm the problem is fixed.",
                `Each must start with "The agent", describe correct behaviour (what it does or does not do), and be verifiable from the agent's steps or final answer.`,
                "Do not reference this particular run's incidental details (file contents, dates, IDs); describe the behaviour.",
            ].join("\n"),
            `# Agent\n${agent}\n\n# Task\n${transcript.input}\n\n# Problems a judge found\n${reason}\n\n# Transcript of the run\n${transcript.text}`,
        );
        return assertions;
    } catch (err) {
        console.warn(`[skill-evals] assertion generation failed for ${agent}, using the judge reason:`, err);
        return fallback;
    }
}

export async function evaluateAgentTraces(
    transcript: Transcript,
    agentName: string,
    globalAssertions: string[],
    options: AgentEvalOptions = {},
): Promise<AgentEvalResult> {
    const { department = "orchestrator", rubric = DEFAULT_RUBRIC, threshold = 0.5, minCases = 10, opikTraceId, onReady } = options;

    const judged = await judgeTranscript(rubric, agentName, transcript);
    const reason = judged.reason;

    if (judged.value >= threshold) {
        return { score: judged.value, reason, inserted: false, count: undefined, readyForEvolution: false };
    }

    const suiteName = skillEvalSuiteName(agentName);
    const suite = await TestSuite.getOrCreate(client, {
        name: suiteName,
        description: `Low-scoring runs of ${agentName}, replayed to check skill changes`,
        projectName: PROJECT_NAME,
        globalAssertions, // only applied when the suite is first created
        globalExecutionPolicy: { runsPerItem: 2, passThreshold: 2 },
    });

    let inserted = false;
    if (!hasCase(await suite.getItems(), transcript.threadId, transcript.checkpointId)) {
        const assertions = await deriveAssertions(agentName, transcript, reason ?? "The run scored below the quality threshold.");
        await suite.insert([
            buildSkillEvalItem({
                agent: agentName,
                department,
                transcript,
                input: transcript.input,
                judge: { name: judged.name, model: JUDGE_MODEL, score: judged.value, threshold, reason: reason ?? "" },
                assertions,
                ...(opikTraceId ? { opikTraceId } : {}),
            }),
        ]);
        inserted = true;
    }

    const count = (await suite.getItemsCount()) ?? 0;
    const readyForEvolution = count >= minCases;
    if (readyForEvolution) await onReady?.({ agent: agentName, suiteName, count });

    return { score: judged.value, reason, inserted, count, readyForEvolution };
}
