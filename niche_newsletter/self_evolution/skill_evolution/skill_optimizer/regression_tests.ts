// What the skill optimizer workflow calls after it edits a skill: replays the agent's stored
// regression cases and returns pass/fail plus a report the optimizer can act on.
//
// The replay runs in a child process (run_regression.ts). EVAL_MODE and DATA_ROOT must be set
// before any agent module is imported, which can't be guaranteed in this process: it may have
// loaded the real agents already, and the swap would not reach them.

import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { AgentName } from "../../../eval/problems/types.js";

export type CaseResult = {
    case_id: string;
    description: string;
    passed: boolean;
    scores: Record<string, number>;
    reasons: string[];
};

export type RegressionResult = {
    passed: boolean;
    passRate: number;
    casesRun: number;
    /** Suite items that could not be replayed (wrong schema version, no assertions). */
    skipped: number;
    cases: CaseResult[];
    /** Plain-text summary of what failed and why; feed it back to the optimizer. */
    report: string;
    /** Set when the run itself could not finish. `passed` is false, but the skill is not to blame. */
    error?: string;
};

export type RegressionOptions = {
    /** Minimum share of a case's assertions that must pass. */
    threshold?: number;
    /** Minimum share of cases that must pass. */
    minPassRate?: number;
    /** Cap on the whole run; cases run one at a time, each with its own timeout. */
    timeoutMs?: number;
};

const RUNNER = fileURLToPath(new URL("./run_regression.ts", import.meta.url));
const OUTPUT_TAIL_CHARS = 4000;

function failure(error: string): RegressionResult {
    return { passed: false, passRate: 0, casesRun: 0, skipped: 0, cases: [], report: `Regression run could not complete: ${error}`, error };
}

/** `agentName` can be any specialist; "system" (the orchestrator) is rejected, it writes its own skills. */
export async function runRegression(agentName: AgentName, options: RegressionOptions = {}): Promise<RegressionResult> {
    const { threshold = 0.8, minPassRate = 0.8, timeoutMs = 2 * 60 * 60_000 } = options;
    const workDir = await mkdtemp(join(tmpdir(), "skill-regression-"));
    const outFile = join(workDir, "result.json");
    try {
        const child = spawn(
            process.execPath,
            ["--import", "tsx", "--import", "dotenv/config", RUNNER, agentName, outFile, "--threshold", String(threshold), "--min-pass-rate", String(minPassRate)],
            { env: { ...process.env, EVAL_MODE: "1" }, stdio: ["ignore", "pipe", "pipe"], timeout: timeoutMs, windowsHide: true },
        );
        // Not forwarded: the parent may be the TUI. Kept only to explain a crash.
        let tail = "";
        const keep = (chunk: Buffer) => { tail = (tail + chunk.toString()).slice(-OUTPUT_TAIL_CHARS); };
        child.stdout.on("data", keep);
        child.stderr.on("data", keep);

        const exit = await new Promise<{ code: number | null; signal: NodeJS.Signals | null }>((resolve, reject) => {
            child.once("error", reject);
            child.once("close", (code, signal) => resolve({ code, signal }));
        });

        try {
            return JSON.parse(await readFile(outFile, "utf-8")) as RegressionResult;
        } catch {
            return failure(`runner exited (code ${exit.code}, signal ${exit.signal}) without writing a result.\n${tail}`);
        }
    } catch (error) {
        return failure(error instanceof Error ? error.message : String(error));
    } finally {
        await rm(workDir, { recursive: true, force: true }).catch(() => undefined);
    }
}
