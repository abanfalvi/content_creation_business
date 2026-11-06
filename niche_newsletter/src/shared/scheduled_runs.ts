import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { dataPaths } from "./paths.js";
import { pullState, pushState } from "./state_sync.js";


export type Repeat = "once" | "daily" | "weekly";
export type ScheduledRun = { id: string; prompt: string; runAt: string; repeat: Repeat; createdAt: string;};

const MAX_PROMPT_LENGTH = 4000;
const MAX_ACTIVE_RUNS = 20;
const MAX_HORIZON_MS = 366 * 24 * 60 * 60 * 1000;
// C0/C1 control chars except \t \n, plus zero-width and bidi override characters, which can hide text from a human reviewing the prompt.
const INVISIBLE_RANGES: [number, number][] = [
    [0x00, 0x08], [0x0b, 0x1f], [0x7f, 0x9f], [0x200b, 0x200f], [0x2028, 0x2029],
    [0x202a, 0x202e], [0x2060, 0x2064], [0x2066, 0x2069], [0xfeff, 0xfeff],
];
const stripInvisible = (text: string) =>
    Array.from(text).filter((ch) => {
        const code = ch.codePointAt(0)!;
        return !INVISIBLE_RANGES.some(([from, to]) => code >= from && code <= to);
    }).join("");

// The prompt is stored and later run unattended, so it is cleaned and bounded here, not trusted.
// (It never reaches a command line: the task only carries the generated run id.)
export function sanitizePrompt(prompt: string): string {
    const cleaned = stripInvisible(prompt.normalize("NFC").replace(/\r\n?/g, "\n")).trim();
    if (!cleaned) throw new Error("The prompt is empty.");
    if (cleaned.length > MAX_PROMPT_LENGTH) {
        throw new Error(`The prompt is ${cleaned.length} characters; the limit is ${MAX_PROMPT_LENGTH}. Shorten it.`);
    }
    return cleaned;
}

const TASK_FOLDER = "\\niche_newsletter\\";
const PROJECT_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RUNNER_SCRIPT = join(PROJECT_ROOT, "src", "run_scheduled.ts");
const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function readAll(): ScheduledRun[] {
    try {
        return JSON.parse(readFileSync(dataPaths.scheduledRuns(), "utf-8")) as ScheduledRun[];
    } catch {
        return [];
    }
}

function writeAll(runs: ScheduledRun[]): void {
    const file = dataPaths.scheduledRuns();
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, JSON.stringify(runs, null, 2));
}

// Parameters travel as environment variables so nothing user-written is ever parsed as PowerShell.
function powershell(script: string, env: Record<string, string>): void {
    if (process.platform !== "win32") throw new Error("Scheduling uses Windows Task Scheduler and only works on Windows.");
    try {
        execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", `$ErrorActionPreference='Stop'; ${script}`], {
            env: { ...process.env, ...env },
            stdio: ["ignore", "pipe", "pipe"],
            encoding: "utf-8",
        });
    } catch (error) {
        const stderr = (error as { stderr?: string }).stderr?.trim();
        throw new Error(`Task Scheduler call failed: ${stderr || String(error)}`);
    }
}

function registerOsTask(run: ScheduledRun): void {
    const at = new Date(run.runAt);
    powershell(
        `$at = [DateTimeOffset]::Parse($env:NL_RUN_AT).LocalDateTime;
        switch ($env:NL_REPEAT) {
            'daily'  { $trigger = New-ScheduledTaskTrigger -Daily -At $at }
            'weekly' { $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $env:NL_DAY -At $at }
            default  { $trigger = New-ScheduledTaskTrigger -Once -At $at }
        }
        $action = New-ScheduledTaskAction -Execute $env:NL_NODE -Argument $env:NL_ARGS -WorkingDirectory $env:NL_CWD;
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3);
        Register-ScheduledTask -TaskName $env:NL_NAME -TaskPath $env:NL_FOLDER -Trigger $trigger -Action $action -Settings $settings -Description $env:NL_DESC -Force | Out-Null`,
        {
            NL_RUN_AT: run.runAt,
            NL_REPEAT: run.repeat,
            NL_DAY: DAYS[at.getDay()]!,
            NL_NODE: process.execPath,
            NL_ARGS: `--import tsx --import dotenv/config "${RUNNER_SCRIPT}" ${run.id}`,
            NL_CWD: PROJECT_ROOT,
            NL_NAME: run.id,
            NL_FOLDER: TASK_FOLDER,
            NL_DESC: "Scheduled niche_newsletter orchestrator run (created by the orchestrator agent)",
        },
    );
}

function unregisterOsTask(id: string): void {
    powershell(
        `Unregister-ScheduledTask -TaskName $env:NL_NAME -TaskPath $env:NL_FOLDER -Confirm:$false -ErrorAction SilentlyContinue`,
        { NL_NAME: id, NL_FOLDER: TASK_FOLDER },
    );
}

// The GitHub runner decides what is due from the pushed registry, so edits start from the latest one and
// must be pushed to count. Both do nothing unless DATA_ROOT is a clone of the state repo (see state_sync.ts).
function pullRegistry(): void {
    try {
        pullState();
    } catch (error) {
        throw new Error(`Could not update the state repo before changing the schedule, so nothing was changed: ${error instanceof Error ? error.message : error}`);
    }
}

function pushRegistry(message: string): void {
    try {
        pushState(message);
    } catch (error) {
        throw new Error(`The schedule was changed locally, but pushing it to the state repo failed (${error instanceof Error ? error.message : error}). Until it is pushed, the scheduled runs on GitHub won't see the change. Run "npm run state:sync" to retry.`);
    }
}

export function listScheduledRuns(): ScheduledRun[] {
    return readAll().sort((a, b) => a.runAt.localeCompare(b.runAt));
}

export function getScheduledRun(id: string): ScheduledRun | undefined {
    return readAll().find((r) => r.id === id);
}

export function listDueScheduledRuns(now = new Date()): ScheduledRun[] {
    return listScheduledRuns().filter((r) => new Date(r.runAt) <= now);
}

// Called by the launcher before it starts a run: a one-off is dropped, a repeating run moves to its next
// slot after now (missed slots are skipped, not caught up). Done up front so a crashed run isn't retried
// on the next tick, which matters when a run can publish.
export function completeScheduledRun(id: string, now = new Date()): void {
    const runs = readAll();
    const run = runs.find((r) => r.id === id);
    if (!run) return;
    if (run.repeat === "once") {
        writeAll(runs.filter((r) => r.id !== id));
        return;
    }
    const step = (run.repeat === "daily" ? 1 : 7) * 24 * 60 * 60 * 1000;
    let next = new Date(run.runAt).getTime();
    while (next <= now.getTime()) next += step;
    run.runAt = new Date(next).toISOString();
    writeAll(runs);
}

export function addScheduledRun(prompt: string, runAt: Date, repeat: Repeat): ScheduledRun {
    if (runAt.getTime() - Date.now() > MAX_HORIZON_MS) throw new Error("Runs can be scheduled at most a year ahead.");
    pullRegistry();
    const existing = readAll();
    if (existing.length >= MAX_ACTIVE_RUNS) {
        throw new Error(`There are already ${MAX_ACTIVE_RUNS} scheduled runs (the limit). Cancel one first.`);
    }
    const run: ScheduledRun = {
        id: randomUUID().slice(0, 8),
        prompt: sanitizePrompt(prompt),
        runAt: runAt.toISOString(),
        repeat,
        createdAt: new Date().toISOString(),
    };
    // registerOsTask(run);
    writeAll([...existing, run]);
    pushRegistry(`Schedule run ${run.id}`);
    return run;
}

// Removes the registry entry and pushes the change to the state repo. False if no such run exists.
export function cancelScheduledRun(id: string): boolean {
    pullRegistry();
    const runs = readAll();
    const remaining = runs.filter((r) => r.id !== id);
    if (remaining.length === runs.length) return false;
    // unregisterOsTask(id);
    writeAll(remaining);
    pushRegistry(`Cancel scheduled run ${id}`);
    return true;
}
