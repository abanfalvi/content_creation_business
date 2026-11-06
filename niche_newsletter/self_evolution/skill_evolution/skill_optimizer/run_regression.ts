// Child-process entry for the skill optimizer's regression gate (see regression_tests.ts).
// Replays the agent's `${agent}_skill_evals` test suite through the eval harness, so every write
// tool is a recorder (EVAL_MODE) and the agents work in a throwaway DATA_ROOT.
//
// Usage: node --import tsx --import dotenv/config self_evolution/skill_evolution/skill_optimizer/run_regression.ts <agent> <result.json> [--threshold 0.8] [--min-pass-rate 0.8]

import { writeFile } from "node:fs/promises";
import { Opik, evaluate } from "opik";
import { MODELS } from "../../../src/models.js";
import { AssertionJudge, RunCompleted, ToolPolicy } from "../../../eval/harness/metrics.js";
import { createDataRoot, removeDataRoot } from "../../../eval/harness/fixtures.js";
import { AGENTS, runProblem } from "../../../eval/harness/run_agent.js";
import type { AgentName, EvalProblem } from "../../../eval/problems/types.js";
import { skillEvalSuiteName, type SkillEvalItemData } from "../trace_schema.js";
import type { CaseResult, RegressionResult } from "./regression_tests.js";

// Must be set before any agent module loads: the MCP loaders read it to swap write tools
// (beehiiv, Notion, Buffer) for recorders. Agents are imported lazily in run_agent.ts.
process.env.EVAL_MODE = "1";

const PROJECT_NAME = "niche_newsletter";

const EXCLUDED_AGENTS = new Set<AgentName>(["system", "memory_agent"]);
// Same split as eval/problems: these run the web-search pipeline or e2b.
const EXPENSIVE_AGENTS = new Set<AgentName>(["research_agent", "dig_prod_creator_agent"]);
// These stop at a human-review gate, so a replay that pauses there is a finished run.
const REVIEW_GATE_AGENTS = new Set<AgentName>(["sm_agent", "dig_prod_creator_agent"]);

function isSkillEvalData(value: unknown): value is SkillEvalItemData {
    const data = value as Partial<SkillEvalItemData> | null;
    return typeof data === "object" && data !== null && data.schemaVersion === 1 && typeof data.replay?.input === "string";
}

function parseArgs(argv: string[]) {
    const [agent, , ...flags] = argv;
    const allowed = Object.keys(AGENTS).filter((name) => !EXCLUDED_AGENTS.has(name as AgentName));
    if (!agent || !allowed.includes(agent)) {
        throw new Error(`Unknown agent "${agent}". Expected one of: ${allowed.join(", ")}.`);
    }
    let threshold = 0.8;
    let minPassRate = 0.8;
    for (let i = 0; i < flags.length; i++) {
        if (flags[i] === "--threshold") threshold = Number(flags[++i]);
        else if (flags[i] === "--min-pass-rate") minPassRate = Number(flags[++i]);
    }
    return { agent: agent as AgentName, threshold, minPassRate };
}

async function waitForItems(dataset: { getItemsCount(): Promise<number | undefined> }, expected: number): Promise<void> {
    for (let attempt = 0; attempt < 20; attempt++) {
        if ((await dataset.getItemsCount()) === expected) return;
        await new Promise((resolve) => setTimeout(resolve, 500));
    }
}

function buildReport(agent: AgentName, cases: CaseResult[], skipped: number, passRate: number, minPassRate: number): string {
    const passedCount = cases.filter((c) => c.passed).length;
    const lines = [`Regression run for ${agent}: ${passedCount}/${cases.length} cases passed (${(passRate * 100).toFixed(0)}%), required ${(minPassRate * 100).toFixed(0)}%.`];
    if (skipped > 0) lines.push(`${skipped} suite item(s) were skipped (wrong schema version or no assertions).`);
    for (const c of cases.filter((c) => !c.passed)) {
        lines.push(`\nFAILED: ${c.description || c.case_id}`);
        for (const reason of c.reasons) lines.push(`  ${reason.replace(/\n/g, "\n  ")}`);
    }
    return lines.join("\n");
}

async function run({ agent, threshold, minPassRate }: ReturnType<typeof parseArgs>): Promise<RegressionResult> {
    const client = new Opik({ projectName: PROJECT_NAME });
    const suite = await client.getOrCreateTestSuite({ name: skillEvalSuiteName(agent), projectName: PROJECT_NAME });
    const [items, globalAssertions] = await Promise.all([suite.getItems(), suite.getGlobalAssertions()]);

    const problems: EvalProblem[] = [];
    let skipped = 0;
    for (const item of items) {
        const assertions = [...globalAssertions, ...item.assertions];
        if (!isSkillEvalData(item.data) || assertions.length === 0) {
            skipped += 1;
            continue;
        }
        problems.push({
            case_id: item.id,
            agent,
            cost: EXPENSIVE_AGENTS.has(agent) ? "expensive" : "standard",
            description: item.description ?? item.data.judge?.reason?.slice(0, 200) ?? item.id,
            message: item.data.replay.input,
            assertions,
            ...(REVIEW_GATE_AGENTS.has(agent) ? { expects_interrupt: true } : {}),
        });
    }
    if (problems.length === 0) {
        return { passed: true, passRate: 1, casesRun: 0, skipped, cases: [], report: `No regression cases for ${agent} (${skipped} skipped): nothing was verified.` };
    }

    const runId = new Date().toISOString().replace(/[:.]/g, "-");
    const dataRoot = await createDataRoot();
    try {
        // The suite is the source of truth: the dataset is rebuilt each run, as in eval/run.ts.
        const dataset = await client.getOrCreateDataset(`${PROJECT_NAME}-skill-regression-${agent}`, `Skill regression cases replayed for ${agent}`, PROJECT_NAME);
        await dataset.clear();
        await dataset.insert(problems.map((problem) => JSON.parse(JSON.stringify(problem))));
        await waitForItems(dataset, problems.length);

        const byId = new Map(problems.map((problem) => [problem.case_id, problem]));
        const result = await evaluate({
            dataset,
            task: async (item) => runProblem(byId.get(String(item.case_id))!, runId),
            scoringMetrics: [new RunCompleted(), new ToolPolicy(), new AssertionJudge()],
            experimentName: `${agent}-skill-regression-${runId}`,
            projectName: PROJECT_NAME,
            experimentConfig: { kind: "skill_regression", judge_model: MODELS.SIGNAL_EDITOR_MANAGER, models: MODELS },
            taskThreads: 1,
        });
        if (result.resultUrl) console.error(`${agent} regression: ${result.resultUrl}`);

        const cases: CaseResult[] = result.testResults.map((test) => {
            const scores = Object.fromEntries(test.scoreResults.map((score) => [score.name, score.value]));
            const caseId = String(test.testCase.scoringInputs.case_id);
            return {
                case_id: caseId,
                description: byId.get(caseId)?.description ?? "",
                passed:
                    (scores.run_completed ?? 0) === 1 &&
                    (scores.tool_policy ?? 1) === 1 &&
                    (scores.assertions_passed ?? 0) >= threshold,
                scores,
                reasons: test.scoreResults.filter((score) => score.value < 1 && score.reason).map((score) => `[${score.name}] ${score.reason}`),
            };
        });
        const passRate = cases.filter((c) => c.passed).length / cases.length;
        return {
            passed: passRate >= minPassRate,
            passRate,
            casesRun: cases.length,
            skipped,
            cases,
            report: buildReport(agent, cases, skipped, passRate, minPassRate),
        };
    } finally {
        await client.flush();
        await removeDataRoot(dataRoot);
    }
}

async function main(): Promise<number> {
    const outFile = process.argv[3];
    let result: RegressionResult;
    try {
        result = await run(parseArgs(process.argv.slice(2)));
    } catch (error) {
        const message = error instanceof Error ? (error.stack ?? error.message) : String(error);
        result = { passed: false, passRate: 0, casesRun: 0, skipped: 0, cases: [], report: `Regression run could not complete: ${message}`, error: message };
    }
    if (outFile) await writeFile(outFile, JSON.stringify(result));
    return result.error ? 2 : result.passed ? 0 : 1;
}

// MCP clients keep sockets open, so exit explicitly once the result is written.
main().then(
    (code) => process.exit(code),
    (error) => {
        console.error(error);
        process.exit(2);
    },
);
