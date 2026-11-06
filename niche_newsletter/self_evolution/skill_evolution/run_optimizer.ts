// Entry point for the weekly skill-optimizer GitHub Action (.github/workflows/skill-optimizer.yml).
//
//   due <out.json> [--limit 10] [--agents a,b]   Writes which agents' test suites hold `limit` or more cases.
//   run <agent> <out.json>                        Runs the optimizer workflow on that agent's suite.
//   consume <agent> <result.json>                 Deletes the cases that `run` used from the suite.
//
// `run` exits 0 when the regression gate approved the new skills, 1 when it rejected them, 2 on an error.
// Cases are only deleted by `consume`, which the workflow calls once the skills are in a PR, so the next
// run starts from an empty suite and sees only cases captured after this one.
//
// Usage: node --import tsx --import dotenv/config self_evolution/skill_evolution/run_optimizer.ts ...

import { cpSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { Opik, TestSuite } from "opik";
import type { AgentName } from "../../eval/problems/types.js";
import { skillEvalSuiteName, type SkillEvalItemData } from "./trace_schema.js";
import type { Transcript } from "./trace_transcript.js";
import { isSkillEvalData } from "./skill_optimizer/utils.js";

const PROJECT_NAME = "niche_newsletter";
const DEFAULT_LIMIT = 10;
// Same exclusions as the regression gate: the orchestrator writes its own skills, the memory agent has no suite.
const OPTIMIZABLE: AgentName[] = [
    "research_agent",
    "rel_filter_agent",
    "use_case_writer_agent",
    "editor_agent",
    "sm_agent",
    "dig_prod_creator_agent",
];
// Keeps ten transcripts inside the summariser's context.
const MAX_CASE_CHARS = 15_000;
const LIVE_SKILLS_DIR = "src/skills";

async function suiteSize(client: Opik, agent: AgentName): Promise<number> {
    try {
        const suite = await TestSuite.get(client, skillEvalSuiteName(agent), PROJECT_NAME);
        return (await suite.getItemsCount()) ?? 0;
    } catch {
        return 0; // no suite yet: nothing has been captured for this agent
    }
}

async function due(outFile: string, flags: string[]): Promise<void> {
    let limit = DEFAULT_LIMIT;
    let only: string[] | undefined;
    for (let i = 0; i < flags.length; i++) {
        if (flags[i] === "--limit") limit = Number(flags[++i]);
        else if (flags[i] === "--agents") only = flags[++i]?.split(/[\s,]+/).filter(Boolean);
    }
    if (!Number.isFinite(limit) || limit < 1) throw new Error(`--limit must be a positive number, got "${limit}".`);
    const unknown = only?.filter((name) => !OPTIMIZABLE.includes(name as AgentName));
    if (unknown?.length) throw new Error(`Unknown agent(s): ${unknown.join(", ")}. Expected: ${OPTIMIZABLE.join(", ")}.`);

    const client = new Opik({ projectName: PROJECT_NAME });
    const rows = [];
    for (const agent of OPTIMIZABLE.filter((name) => !only || only.includes(name))) {
        const count = await suiteSize(client, agent);
        rows.push({ agent, count, due: count >= limit });
        console.error(`${agent}: ${count} cases (limit ${limit})${count >= limit ? " -> due" : ""}`);
    }
    await client.flush();
    writeFileSync(outFile, JSON.stringify({ limit, rows, due: rows.filter((row) => row.due) }, null, 2));
}

/** The workflow takes one transcript; this stacks every suite case into one, each labelled with why it was captured. */
function combine(agent: AgentName, cases: SkillEvalItemData[]): Transcript {
    const sections = cases.map((c, i) =>
        [
            `## Case ${i + 1} of ${cases.length}`,
            `Task given to the agent: ${c.replay.originalInput ?? c.replay.input}`,
            `Judge score ${c.judge?.score?.toFixed(2) ?? "?"}: ${c.judge?.reason ?? "(no reason recorded)"}`,
            "",
            c.transcript.length > MAX_CASE_CHARS ? `${c.transcript.slice(0, MAX_CASE_CHARS)}\n…[transcript clipped]` : c.transcript,
        ].join("\n"),
    );
    const sum = (pick: (c: SkillEvalItemData) => number) => cases.reduce((total, c) => total + (pick(c) || 0), 0);
    return {
        threadId: `skill_evals:${agent}`,
        checkpointId: "",
        checkpointNs: "",
        steps: [],
        input: cases.map((c) => c.replay.originalInput ?? c.replay.input).join("\n---\n"),
        skillsRead: [...new Set(cases.flatMap((c) => c.skillsRead ?? []))],
        stats: { steps: sum((c) => c.stats?.steps), toolCalls: sum((c) => c.stats?.toolCalls), toolErrors: sum((c) => c.stats?.toolErrors) },
        text: [`These are ${cases.length} separate low-scoring sessions of the ${agent} agent. Look for what they have in common.`, ...sections].join("\n\n---\n\n"),
    };
}

async function run(agent: AgentName, outFile: string): Promise<boolean> {
    if (!OPTIMIZABLE.includes(agent)) throw new Error(`Unknown agent "${agent}". Expected: ${OPTIMIZABLE.join(", ")}.`);

    const client = new Opik({ projectName: PROJECT_NAME });
    const suite = await TestSuite.get(client, skillEvalSuiteName(agent), PROJECT_NAME);
    const items = await suite.getItems();
    const usable = items.filter((item) => isSkillEvalData(item.data));
    const cases = usable.map((item) => item.data as unknown as SkillEvalItemData);
    if (cases.length === 0) throw new Error(`${skillEvalSuiteName(agent)} has no usable cases (${items.length} items).`);

    // Imported here so `due` stays cheap: agent.ts reads its prompts and builds three models at import.
    const { skillOptimizerWorkflow, TMP_SKILLS_DIR, emptyDir } = await import("./skill_optimizer/agent.js");

    // The optimizer edits a copy of the live skills, and the regression run (a child process that inherits
    // this variable) reads that copy. src/skills changes only if save_skills runs, i.e. the gate approved.
    emptyDir(TMP_SKILLS_DIR);
    if (existsSync(LIVE_SKILLS_DIR)) cpSync(LIVE_SKILLS_DIR, TMP_SKILLS_DIR, { recursive: true });
    process.env.SKILLS_ROOT = resolve(TMP_SKILLS_DIR);

    let final;
    try {
        final = await skillOptimizerWorkflow.invoke({
            agentName: agent,
            traceTranscript: combine(agent, cases),
        });
    } finally {
        // Already empty after save_skills; this clears the rejected or crashed attempts.
        emptyDir(TMP_SKILLS_DIR);
    }

    const approved = final.regressionPass === true;

    writeFileSync(
        outFile,
        JSON.stringify(
            { agent, approved, attempts: final.history.length, cases: cases.length, caseIds: usable.map((item) => item.id), report: final.regressionReport, optimizerActions: final.optimizerActions },
            null,
            2,
        ),
    );
    await client.flush();
    return approved;
}

/** Deletes exactly the cases the run used; cases captured while it ran stay for the next one. */
async function consume(agent: AgentName, resultFile: string): Promise<void> {
    if (!OPTIMIZABLE.includes(agent)) throw new Error(`Unknown agent "${agent}". Expected: ${OPTIMIZABLE.join(", ")}.`);
    const { caseIds } = JSON.parse(readFileSync(resultFile, "utf-8")) as { caseIds?: string[] };
    if (!caseIds?.length) throw new Error(`${resultFile} lists no cases to delete.`);

    const client = new Opik({ projectName: PROJECT_NAME });
    const suite = await TestSuite.get(client, skillEvalSuiteName(agent), PROJECT_NAME);
    await suite.delete(caseIds);
    await client.flush();
    console.error(`${agent}: deleted ${caseIds.length} used case(s) from ${skillEvalSuiteName(agent)}.`);
}

async function main(): Promise<number> {
    const [command, first, second, ...flags] = process.argv.slice(2);
    if (command === "due" && first) {
        await due(first, [second, ...flags].filter((flag): flag is string => flag !== undefined));
        return 0;
    }
    if (command === "run" && first && second) return (await run(first as AgentName, second)) ? 0 : 1;
    if (command === "consume" && first && second) {
        await consume(first as AgentName, second);
        return 0;
    }
    throw new Error("Usage: run_optimizer.ts due <out.json> [--limit N] [--agents a,b] | run <agent> <out.json> | consume <agent> <result.json>");
}

main().then(
    (code) => process.exit(code),
    (error) => {
        console.error(error);
        process.exit(2);
    },
);
