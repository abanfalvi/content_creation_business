import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { dataPaths } from "./paths.js";


export type Repeat = "once" | "daily" | "weekly";
// allowDistribution: the unattended run may call the distribution manager (publishing / outreach).
export type ScheduledRun = { id: string; prompt: string; runAt: string; repeat: Repeat; createdAt: string; allowDistribution?: boolean };

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

export function listScheduledRuns(): ScheduledRun[] {
    return readAll().sort((a, b) => a.runAt.localeCompare(b.runAt));
}

export function getScheduledRun(id: string): ScheduledRun | undefined {
    return readAll().find((r) => r.id === id);
}

export function addScheduledRun(prompt: string, runAt: Date, repeat: Repeat, allowDistribution = false): ScheduledRun {
    if (runAt.getTime() - Date.now() > MAX_HORIZON_MS) throw new Error("Runs can be scheduled at most a year ahead.");
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
        ...(allowDistribution && { allowDistribution }),
    };
    registerOsTask(run);
    writeAll([...existing, run]);
    return run;
}

// Removes the registry entry and its Task Scheduler task. False if no such run exists.
export function cancelScheduledRun(id: string): boolean {
    const runs = readAll();
    const remaining = runs.filter((r) => r.id !== id);
    if (remaining.length === runs.length) return false;
    unregisterOsTask(id);
    writeAll(remaining);
    return true;
}
