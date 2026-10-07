import { join } from "node:path";

// Every on-disk location agents read or write, resolved against DATA_ROOT (default: the
// project root, i.e. today's locations). The eval harness points DATA_ROOT at a temp
// directory so eval runs never touch real notes, strategy docs or checkpoints.
// Resolved at call time, except where a module opens a file once at import (checkpointers).
const root = () => process.env.DATA_ROOT ?? ".";

export const dataPaths = {
    researchScratchPad: () => join(root(), "src/signal-editor-dep/research_agent/scratch_pad/"),
    useCaseScratchPad: () => join(root(), "src/signal-editor-dep/use_case_writer_agent/scratch_pad/"),
    managementNotes: () => join(root(), "management_notes/"),
    contentStrategy: () => join(root(), "management_notes/content_strategy/"),
    contentPlans: () => join(root(), "management_notes/content_plans/"),
    memories: () => join(root(), "memories/"),
    transcriptsDb: () => join(root(), "transcripts/transcripts.db"),
    checkpointDb: (department: "orchestrator" | "distribution-dep" | "curriculum-dep" | "signal-editor-dep") =>
        join(root(), "src", department, ".checkpoints/state.db"),
    sessionsIndex: () => join(root(), "src/orchestrator/.checkpoints/sessions.json"),
    scheduledRuns: () => join(root(), "src/orchestrator/.checkpoints/scheduled_runs.json"),
};
