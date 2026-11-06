import { pullState, pushState, stateRepoDir } from "./shared/state_sync.js";

// npm run state:sync
// Pulls what the GitHub runner pushed, then commits and pushes local changes to memories, notes and the
// schedule. Run it before and after working with the TUI so both sides see the same state.

const dir = stateRepoDir();
if (!dir) {
    console.error("DATA_ROOT is not set to a clone of the state repo (a folder with a .git), so there is nothing to sync.");
    process.exit(1);
}

try {
    pullState();
    const pushed = pushState("Sync state from local");
    console.log(pushed ? `Pushed local changes in ${dir}.` : `Nothing new to commit in ${dir}; up to date.`);
} catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
}
