import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

// Keeps a local clone of the private state repo in step with GitHub. Scheduled runs happen on a GitHub runner
// that only sees what has been pushed there, and the runner pushes its own changes back, so the local side
// pulls before it edits and pushes after.
//
// This only does anything when DATA_ROOT points at a git checkout (the state repo clone). In every other
// case (DATA_ROOT unset, so the project itself, or an eval's temp directory) it does nothing.

export function stateRepoDir(): string | undefined {
    // The scheduler job commits the state itself, and the sandbox has no git repo.
    if (process.env.CI || process.env.NL_SCHEDULED_RUN) return undefined;
    const dir = resolve(process.env.DATA_ROOT ?? ".");
    return existsSync(join(dir, ".git")) ? dir : undefined;
}

function git(dir: string, args: string[]): { status: number; stdout: string } {
    const result = spawnSync("git", ["-C", dir, ...args], { encoding: "utf-8" });
    if (result.error) throw new Error(`git could not run: ${result.error.message}`);
    return { status: result.status ?? 1, stdout: result.stdout.trim() };
}

function gitOrThrow(dir: string, args: string[]): void {
    const result = spawnSync("git", ["-C", dir, ...args], { encoding: "utf-8" });
    if (result.error) throw new Error(`git could not run: ${result.error.message}`);
    if (result.status !== 0) throw new Error(`git ${args.join(" ")} failed: ${(result.stderr || result.stdout).trim()}`);
}

// Fetches what the runner (or another machine) pushed. Local uncommitted changes are set aside and put back.
export function pullState(): void {
    const dir = stateRepoDir();
    if (!dir) return;
    gitOrThrow(dir, ["pull", "--rebase", "--autostash"]);
}

// Commits whatever changed in the state repo and pushes it. Returns false when there was nothing to commit.
export function pushState(message: string): boolean {
    const dir = stateRepoDir();
    if (!dir) return false;
    gitOrThrow(dir, ["add", "-A"]);
    const changed = git(dir, ["diff", "--cached", "--quiet"]).status !== 0;
    if (changed) gitOrThrow(dir, ["commit", "-m", message]);
    // The runner may have pushed in the meantime; this also sends any earlier commit that failed to push.
    gitOrThrow(dir, ["pull", "--rebase"]);
    gitOrThrow(dir, ["push"]);
    return changed;
}
