import { BaseMetric, type EvaluationScoreResult } from "opik";
import { ChatOpenRouter } from "@langchain/openrouter";
import { OpenRouter } from "@openrouter/sdk";
import { z } from "zod";
import { MODELS } from "../../src/models.js";

// Opik's built-in judges only accept OpenAI/Anthropic/Google model IDs; this project
// only has OpenRouter, so the judge runs through ChatOpenRouter instead.
const JUDGE_MODEL = MODELS.SIGNAL_EDITOR_MANAGER;

const verdictSchema = z.object({
    results: z.array(z.object({
        index: z.number().describe("1-based index of the assertion"),
        passed: z.boolean(),
        reason: z.string().describe("One sentence citing the evidence from the run, or what is missing"),
    })),
});

const JUDGE_INSTRUCTIONS = `You grade one run of an AI agent against a list of assertions.
Judge each assertion independently, using only the run record below. An assertion passes only if the record shows clear evidence for it; if the evidence is missing, ambiguous, or the run errored before the relevant step, it fails.
"Write calls intercepted by the eval guard" were real attempts by the agent that were recorded instead of executed; treat them as the actions the agent took.
Return one result per assertion.`;

type Verdict = z.infer<typeof verdictSchema>;
type JudgeReply = { raw: { content: unknown; response_metadata?: Record<string, unknown> }; parsed: Verdict | null | undefined };

// includeRaw: when the model answers in prose instead of calling the verdict tool (or its
// reply is cut off), `parsed` is empty and the raw reply says why.
let judge: { invoke(input: unknown): Promise<unknown> } | null = null;
function getJudge() {
    judge ??= new ChatOpenRouter({ model: JUDGE_MODEL, temperature: 0, maxTokens: 15000, maxRetries: 2 })
        .withStructuredOutput(verdictSchema, { method: "functionCalling", includeRaw: true });
    return judge;
}

const JUDGE_ATTEMPTS = 2;

export class AssertionJudge extends BaseMetric {
    readonly validationSchema = z.object({
        case_id: z.string(),
        description: z.string(),
        assertions: z.array(z.string()),
        output: z.string(),
        handoff: z.unknown().optional(),
        message: z.string().optional(),
    });

    constructor() {
        super("assertions_passed");
    }

    async score(input: unknown): Promise<EvaluationScoreResult> {
        const { description, assertions, output, handoff, message } = this.validationSchema.parse(input);
        const task = message ?? JSON.stringify(handoff, null, 2);
        const numbered = assertions.map((assertion, i) => `${i + 1}. ${assertion}`).join("\n");

        const prompt = [
            { role: "system", content: JUDGE_INSTRUCTIONS },
            { role: "user", content: `# Case\n${description}\n\n# Task given to the agent\n${task}\n\n# Assertions\n${numbered}\n\n# Run record\n${output}` },
        ];
        let verdict: Verdict | undefined;
        let lastReply: JudgeReply | undefined;
        for (let attempt = 0; attempt < JUDGE_ATTEMPTS && !verdict?.results; attempt++) {
            lastReply = (await getJudge().invoke(prompt)) as JudgeReply;
            verdict = lastReply.parsed ?? undefined;
        }
        if (!verdict?.results) {
            const finish = lastReply?.raw.response_metadata?.finish_reason ?? "unknown";
            const text = typeof lastReply?.raw.content === "string" ? lastReply.raw.content : JSON.stringify(lastReply?.raw.content ?? "");
            return {
                name: this.name,
                value: 0,
                reason: `Judge returned no verdict after ${JUDGE_ATTEMPTS} attempts (finish_reason: ${finish}; run record ${output.length} chars). Reply: ${text.slice(0, 300) || "(empty)"}`,
            };
        }

        const byIndex = new Map(verdict.results.map((result) => [result.index, result]));
        const failures: string[] = [];
        let passed = 0;
        assertions.forEach((assertion, i) => {
            const result = byIndex.get(i + 1);
            if (result?.passed) passed += 1;
            else failures.push(`✗ ${assertion} — ${result?.reason ?? "judge returned no verdict"}`);
        });

        return {
            name: this.name,
            value: passed / assertions.length,
            reason: failures.length === 0 ? "All assertions passed." : failures.join("\n"),
        };
    }
}

export class ToolPolicy extends BaseMetric {
    readonly validationSchema = z.object({
        tool_calls: z.array(z.string()),
        error: z.string().nullable(),
        required_tools: z.array(z.string()).optional(),
        forbidden_tools: z.array(z.string()).optional(),
    });

    constructor() {
        super("tool_policy");
    }

    score(input: unknown): EvaluationScoreResult[] {
        const { tool_calls, error, required_tools = [], forbidden_tools = [] } = this.validationSchema.parse(input);
        // A crashed run's tool calls are unknown; run_completed already reports the failure.
        if (error || (required_tools.length === 0 && forbidden_tools.length === 0)) return [];

        const called = new Set(tool_calls);
        const violations = [
            ...required_tools.filter((name) => !called.has(name)).map((name) => `required tool never called: ${name}`),
            ...forbidden_tools.filter((name) => called.has(name)).map((name) => `forbidden tool called: ${name}`),
        ];
        return [{ name: this.name, value: violations.length === 0 ? 1 : 0, reason: violations.join("; ") || "Tool policy satisfied." }];
    }
}

export class RunCompleted extends BaseMetric {
    readonly validationSchema = z.object({
        error: z.string().nullable(),
        interrupted: z.boolean(),
        expects_interrupt: z.boolean().optional(),
    });

    constructor() {
        super("run_completed");
    }

    score(input: unknown): EvaluationScoreResult {
        const { error, interrupted, expects_interrupt = false } = this.validationSchema.parse(input);
        if (error) return { name: this.name, value: 0, reason: `Run failed: ${error}` };
        if (expects_interrupt && !interrupted) return { name: this.name, value: 0, reason: "Expected the run to pause at the review gate, but it finished without pausing." };
        if (!expects_interrupt && interrupted) return { name: this.name, value: 0, reason: "The run paused for review unexpectedly." };
        return { name: this.name, value: 1, reason: expects_interrupt ? "Paused at the review gate as expected." : "Run finished." };
    }
}
