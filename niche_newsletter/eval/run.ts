// Usage:
//   npx tsx --import dotenv/config eval/run.ts [suite...] [--include-expensive] [--case <case_id>] [--threshold 0.8] [--min-pass-rate 0.8]
// Suites: research_agent, rel_filter_agent, use_case_writer_agent, editor_agent, sm_agent,
// dig_prod_creator_agent, memory_agent, system, specialists, all (default).

import { Opik, evaluate } from "opik";
import { MODELS } from "../src/models.js";
import { AssertionJudge, RunCompleted, ToolPolicy } from "./harness/metrics.js";
import { createDataRoot, removeDataRoot } from "./harness/fixtures.js";
import { runProblem } from "./harness/run_agent.js";
import { specialistProblems } from "./problems/specialists.js";
import { systemProblems } from "./problems/system.js";
import type { AgentName, EvalProblem } from "./problems/types.js";

// Must be set before any agent module loads: the MCP loaders read it to swap write
// tools (beehiiv, Notion, Buffer) for recorders. Agents are imported lazily in run_agent.ts.
process.env.EVAL_MODE = "1";

const PROJECT_NAME = "niche_newsletter";
const SPECIALISTS: AgentName[] = ["research_agent", "rel_filter_agent", "use_case_writer_agent", "editor_agent", "sm_agent", "dig_prod_creator_agent", "memory_agent"];

function parseArgs(argv: string[]) {
    const suites: string[] = [];
    let includeExpensive = false;
    let caseId: string | undefined;
    let threshold = 0.8;
    let minPassRate = 0.8;
    for (let i = 0; i < argv.length; i++) {
        const arg = argv[i]!;
        if (arg === "--include-expensive") includeExpensive = true;
        else if (arg === "--case") caseId = argv[++i];
        else if (arg === "--threshold") threshold = Number(argv[++i]);
        else if (arg === "--min-pass-rate") minPassRate = Number(argv[++i]);
        else suites.push(arg);
    }
    return { suites: suites.length ? suites : ["all"], includeExpensive, caseId, threshold, minPassRate };
}

function selectAgents(suites: string[]): AgentName[] {
    const agents = new Set<AgentName>();
    for (const suite of suites) {
        if (suite === "all") [...SPECIALISTS, "system" as const].forEach((agent) => agents.add(agent));
        else if (suite === "specialists") SPECIALISTS.forEach((agent) => agents.add(agent));
        else if ([...SPECIALISTS, "system"].includes(suite)) agents.add(suite as AgentName);
        else throw new Error(`Unknown suite "${suite}"`);
    }
    return [...agents];
}

type CaseResult = { agent: AgentName; case_id: string; passed: boolean; scores: Record<string, number>; reasons: string[] };

async function runSuite(client: Opik, agent: AgentName, problems: EvalProblem[], runId: string, threshold: number): Promise<CaseResult[]> {
    const dataset = await client.getOrCreateDataset(`${PROJECT_NAME}-eval-${agent}`, `Eval problems for ${agent}`, PROJECT_NAME);
    // The code is the source of truth: the dataset is replaced each run so edited or
    // removed problems don't linger in Opik.
    await dataset.clear();
    await dataset.insert(problems.map((problem) => JSON.parse(JSON.stringify(problem))));
    await waitForItems(dataset, problems.length);

    const byId = new Map(problems.map((problem) => [problem.case_id, problem]));
    const result = await evaluate({
        dataset,
        task: async (item) => runProblem(byId.get(String(item.case_id))!, runId),
        scoringMetrics: [new RunCompleted(), new ToolPolicy(), new AssertionJudge()],
        experimentName: `${agent}-${runId}`,
        projectName: PROJECT_NAME,
        experimentConfig: { judge_model: process.env.EVAL_JUDGE_MODEL ?? MODELS.SIGNAL_EDITOR_MANAGER, models: MODELS },
    });
    if (result.resultUrl) console.log(`  ${agent}: ${result.resultUrl}`);

    return result.testResults.map((test) => {
        const scores = Object.fromEntries(test.scoreResults.map((score) => [score.name, score.value]));
        const passed =
            (scores.run_completed ?? 0) === 1 &&
            (scores.tool_policy ?? 1) === 1 &&
            (scores.assertions_passed ?? 0) >= threshold;
        const reasons = test.scoreResults.filter((score) => score.value < 1 && score.reason).map((score) => `[${score.name}] ${score.reason}`);
        return { agent, case_id: String(test.testCase.scoringInputs.case_id), passed, scores, reasons };
    });
}

async function waitForItems(dataset: { getItemsCount(): Promise<number | undefined> }, expected: number): Promise<void> {
    for (let attempt = 0; attempt < 20; attempt++) {
        if ((await dataset.getItemsCount()) === expected) return;
        await new Promise((resolve) => setTimeout(resolve, 500));
    }
}

async function main() {
    const { suites, includeExpensive, caseId, threshold, minPassRate } = parseArgs(process.argv.slice(2));
    const agents = selectAgents(suites);
    const selected = [...specialistProblems, ...systemProblems].filter((problem) =>
        agents.includes(problem.agent) &&
        (caseId ? problem.case_id === caseId : includeExpensive || problem.cost === "standard"),
    );
    if (selected.length === 0) {
        console.log("No problems selected (expensive cases need --include-expensive).");
        return 0;
    }

    const runId = new Date().toISOString().replace(/[:.]/g, "-");
    const dataRoot = await createDataRoot();
    console.log(`Agents read and write under ${dataRoot} for this run.`);
    const client = new Opik({ projectName: PROJECT_NAME });
    const results: CaseResult[] = [];
    try {
        for (const agent of agents) {
            const problems = selected.filter((problem) => problem.agent === agent);
            if (problems.length === 0) continue;
            console.log(`Running ${problems.length} case(s) for ${agent}…`);
            results.push(...(await runSuite(client, agent, problems, runId, threshold)));
        }
    } finally {
        await client.flush();
        if (!(await removeDataRoot(dataRoot))) {
            console.log(`Could not delete ${dataRoot} yet (checkpoint files still open); the next run removes it.`);
        }
    }

    console.log("\nResults");
    for (const result of results) {
        const scores = Object.entries(result.scores).map(([name, value]) => `${name}=${value.toFixed(2)}`).join("  ");
        console.log(`${result.passed ? "PASS" : "FAIL"}  ${result.agent}/${result.case_id}  ${scores}`);
        for (const reason of result.reasons) console.log(`      ${reason.replace(/\n/g, "\n      ")}`);
    }
    const passRate = results.filter((result) => result.passed).length / results.length;
    console.log(`\nPass rate: ${(passRate * 100).toFixed(0)}% (${results.filter((r) => r.passed).length}/${results.length}), required ${(minPassRate * 100).toFixed(0)}%`);
    return passRate >= minPassRate ? 0 : 1;
}

// MCP clients keep sockets open, so exit explicitly once results are reported.
main().then(
    (code) => process.exit(code),
    (error) => {
        console.error(error);
        process.exit(1);
    },
);
