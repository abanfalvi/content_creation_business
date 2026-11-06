import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { relative, resolve, sep } from "node:path";
import { CommandExitError, Sandbox } from "e2b";
import { completeScheduledRun, listDueScheduledRuns, listScheduledRuns, type ScheduledRun } from "./shared/scheduled_runs.js";
import { dataPaths } from "./shared/paths.js";

// Runs on the GitHub Actions runner (never inside the sandbox). For each due scheduled run it starts an E2B
// sandbox, uploads the code and the persistent state, runs src/run_scheduled.ts there, and brings the changed
// state back. The workflow commits STATE_DIR afterwards.
//
//   node --import tsx src/launch_scheduled.ts            runs everything that is due
//   node --import tsx src/launch_scheduled.ts <id> ...   runs those ids now, due or not (manual trigger)
//
// STATE_DIR (default "state") is the checked-out state repo. It uses the DATA_ROOT layout (memories/,
// management_notes/, src/orchestrator/.checkpoints/scheduled_runs.json) plus auth/, which holds the OAuth
// token files that live in src/shared/.auth in the project.

const TEMPLATE = "newsletter-scheduled-run";
const HOME = "/home/user";
const DATA_ROOT = `${HOME}/state`;
const AUTH_DIR = `${HOME}/src/shared/.auth`;
const SANDBOX_TIMEOUT_MS = 60 * 60_000;
const MAX_ARCHIVE_BYTES = 100 * 1024 * 1024;
const LOG_TAIL_CHARS = 3000;

const STATE_DIR = resolve(process.env.STATE_DIR ?? "state");
// The registry helpers resolve their paths against DATA_ROOT at call time.
process.env.DATA_ROOT = STATE_DIR;

// Directories under DATA_ROOT that agents read and write, and that come back after the run.
const STATE_ENTRIES = ["memories", "management_notes"];
const CHECKPOINT_DEPARTMENTS = ["orchestrator", "distribution-dep", "curriculum-dep", "signal-editor-dep"];

// Only these reach the sandbox. STATE_REPO_PAT is deliberately not among them.
const FORWARDED_ENV = [
    "OPENROUTER_API_KEY", "BEEHIIV_PUBLICATION_ID", "PARALLEL_SEARCH_API_KEY", "APIFY_API_KEY", "ALPHAXIV_TOKEN",
    "GOOGLE_PROJECT_KEY", "DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN", "DROPBOX",
    "BUFFER_API_KEY", "INSTAGRAM_USER_ID", "INSTAGRAM_ACCESS_TOKEN",
    "NOTION_DRAFT_PAGE", "NOTION_LEADS_PAGE", // page ids the Notion tools may write under
    "E2B_API_KEY", // the editor's visual tool starts its own nested sandbox
    "OPIK_API_KEY", "OPIK_WORKSPACE", "OPIK_URL_OVERRIDE", "NL_CONTEXT_WINDOW",
];

const forwardedEnv = (): Record<string, string> =>
    Object.fromEntries(FORWARDED_ENV.flatMap((name) => (process.env[name] ? [[name, process.env[name]!]] : [])));

// --- archives -------------------------------------------------------------------------------------------

function createArchive(cwd: string, entries: string[]): Buffer {
    return execFileSync("tar", ["-czf", "-", "-C", cwd, "--null", "-T", "-"], {
        input: entries.join("\0"),
        maxBuffer: MAX_ARCHIVE_BYTES,
    });
}

// What the sandbox needs of the project: src (minus the TUI, which isn't used here, except the session index
// that run_scheduled.ts imports) and tsconfig.json for tsx's JSX settings. Asking git keeps .env, .auth,
// checkpoints and other ignored files out, while still including files that are not committed yet.
function codeFiles(): string[] {
    const listed = execFileSync("git", ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "src", "tsconfig.json"], {
        encoding: "utf-8",
        maxBuffer: MAX_ARCHIVE_BYTES,
    });
    return listed
        .split("\0")
        .filter((f) => f && existsSync(f))
        .filter((f) => !f.endsWith(".test.ts"))
        .filter((f) => !f.startsWith("src/tui/") || f === "src/tui/sessions.ts");
}

function toArrayBuffer(buffer: Buffer): ArrayBuffer {
    return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength) as ArrayBuffer;
}

// The archive comes out of a sandbox where an agent has been running, so treat it as untrusted: only plain
// files and directories, and no absolute or ".." paths, so nothing can be written outside the target
// directory (a symlink entry followed by a file "through" it is the classic way out).
function extractArchive(archive: Uint8Array, targetDir: string): void {
    const bytes = Buffer.from(archive);
    if (bytes.length > MAX_ARCHIVE_BYTES) throw new Error(`Archive is ${bytes.length} bytes; refusing to extract it.`);
    const run = (flags: string) => execFileSync("tar", [flags, "-f", "-"], { input: bytes, encoding: "utf-8", maxBuffer: MAX_ARCHIVE_BYTES });

    for (const line of run("-tvz").split("\n").filter(Boolean)) {
        if (line[0] !== "-" && line[0] !== "d") throw new Error(`Archive has a non-regular entry, refusing to extract it: ${line}`);
    }
    for (const name of run("-tz").split("\n").filter(Boolean)) {
        if (name.startsWith("/") || name.split("/").includes("..")) throw new Error(`Archive has an unsafe path, refusing to extract it: ${name}`);
    }
    execFileSync("tar", ["-xzf", "-", "-C", targetDir], { input: bytes, maxBuffer: MAX_ARCHIVE_BYTES });
}

// --- one run --------------------------------------------------------------------------------------------

async function runInSandbox(run: ScheduledRun): Promise<boolean> {
    console.log(`[${run.id}] starting sandbox for: ${run.prompt}`);
    let sandbox: Sandbox;
    try {
        sandbox = await Sandbox.create(TEMPLATE, { timeoutMs: SANDBOX_TIMEOUT_MS });
    } catch (error) {
        console.error(`[${run.id}] could not start the sandbox: ${error}`);
        return false;
    }

    let ok = false;
    try {
        // Registry with just this run: run_scheduled.ts looks its run up by id, and the other prompts stay out.
        const registryPath = `${DATA_ROOT}/${relative(STATE_DIR, dataPaths.scheduledRuns()).split(sep).join("/")}`;
        const stateEntries = STATE_ENTRIES.filter((entry) => existsSync(resolve(STATE_DIR, entry)));
        const authDir = resolve(STATE_DIR, "auth");

        await sandbox.files.write([
            { path: `${HOME}/code.tgz`, data: toArrayBuffer(createArchive(".", codeFiles())) },
            ...(stateEntries.length ? [{ path: `${HOME}/state.tgz`, data: toArrayBuffer(createArchive(STATE_DIR, stateEntries)) }] : []),
            ...(existsSync(authDir) ? [{ path: `${HOME}/auth.tgz`, data: toArrayBuffer(createArchive(authDir, ["."])) }] : []),
            { path: registryPath, data: JSON.stringify([run]) },
        ]);

        // The checkpointers open their SQLite files on import and don't create the directory themselves.
        const checkpointDirs = CHECKPOINT_DEPARTMENTS.map((d) => `${DATA_ROOT}/src/${d}/.checkpoints`).join(" ");
        await sandbox.commands.run(
            [
                `mkdir -p ${DATA_ROOT}/memories ${DATA_ROOT}/management_notes ${AUTH_DIR} ${checkpointDirs}`,
                `tar -xzf code.tgz -C ${HOME}`,
                `[ ! -f state.tgz ] || tar -xzf state.tgz -C ${DATA_ROOT}`,
                `[ ! -f auth.tgz ] || tar -xzf auth.tgz -C ${AUTH_DIR}`,
            ].join(" && "),
            { cwd: HOME, timeoutMs: 120_000 },
        );

        try {
            await sandbox.commands.run(`node --import tsx src/run_scheduled.ts ${run.id}`, {
                cwd: HOME,
                timeoutMs: SANDBOX_TIMEOUT_MS,
                envs: { ...forwardedEnv(), DATA_ROOT },
                onStdout: (data) => { process.stdout.write(data); },
                onStderr: (data) => { process.stderr.write(data); },
            });
            ok = true;
        } catch (error) {
            if (error instanceof CommandExitError) console.error(`[${run.id}] the run exited with code ${error.exitCode}`);
            else console.error(`[${run.id}] the run did not finish: ${error}`);
        }
    } catch (error) {
        console.error(`[${run.id}] sandbox setup failed: ${error}`);
    } finally {
        await collectResults(sandbox, run.id);
        await sandbox.kill().catch(() => {});
    }
    return ok;
}

// Runs after success and failure alike: a failed run can still have refreshed an OAuth token or written a memory.
async function collectResults(sandbox: Sandbox, id: string): Promise<void> {
    try {
        const log = await sandbox.files.read(`${HOME}/logs/scheduled_runs.log`);
        console.log(`[${id}] run log (tail):\n${log.slice(-LOG_TAIL_CHARS)}`);
    } catch {
        console.log(`[${id}] no run log was written`);
    }
    try {
        await sandbox.commands.run(
            `tar -czf ${HOME}/state-out.tgz -C ${DATA_ROOT} ${STATE_ENTRIES.join(" ")} && tar -czf ${HOME}/auth-out.tgz -C ${AUTH_DIR} .`,
            { cwd: HOME, timeoutMs: 120_000 },
        );
        extractArchive(await sandbox.files.read(`${HOME}/state-out.tgz`, { format: "bytes" }), STATE_DIR);
        const authTarget = resolve(STATE_DIR, "auth");
        mkdirSync(authTarget, { recursive: true });
        extractArchive(await sandbox.files.read(`${HOME}/auth-out.tgz`, { format: "bytes" }), authTarget);
        console.log(`[${id}] state brought back`);
    } catch (error) {
        console.error(`[${id}] could not bring the state back, so this run's changes are lost: ${error}`);
    }
}

// --- main -----------------------------------------------------------------------------------------------

if (!process.env.E2B_API_KEY) {
    console.error("E2B_API_KEY is not set.");
    process.exit(1);
}
if (!existsSync(STATE_DIR)) {
    console.error(`State directory ${STATE_DIR} does not exist (set STATE_DIR to the checked-out state repo).`);
    process.exit(1);
}

const requestedIds = process.argv.slice(2);
const runs = requestedIds.length
    ? listScheduledRuns().filter((r) => requestedIds.includes(r.id))
    : listDueScheduledRuns();

for (const id of requestedIds) {
    if (!runs.some((r) => r.id === id)) console.error(`No scheduled run with id "${id}".`);
}
if (!runs.length) console.log("No scheduled runs are due.");

let failed = 0;
// One at a time: runs share the memories and the token files, and each brings its changes back into STATE_DIR.
for (const run of runs) {
    // Advance the schedule first (see completeScheduledRun) so a crash can't make the next tick run it again.
    completeScheduledRun(run.id);
    if (!(await runInSandbox(run))) failed++;
}

console.log(`${runs.length - failed}/${runs.length} scheduled runs succeeded.`);
process.exit(failed ? 1 : 0);
