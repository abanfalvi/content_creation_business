import type { TestSuiteItem } from "opik";
import type { Transcript } from "./trace_transcript.js";

/**
 * One suite per agent: `${agent}_skill_evals`. Everything below lives in a TestSuiteItem's `data`, 
 * bump `schemaVersion` whenever the shape changes.
 */
export interface SkillEvalItemData {
    schemaVersion: 1;
    agent: string;

    /** What the eval task function replays. The suite judge sees whatever the task returns, not this. */
    replay: {
        /** First human message of the run; the prompt the agent is re-run on. */
        input: string;
        /** The run's real first message, kept once the optimizer has shortened `input` for cheaper replays. Always refine from this, never from `input`. */
        originalInput?: string;
        /** Checkpoint to resume from instead of starting fresh. Omit to start from `input`. */
        resumeFrom?: { threadId: string; checkpointNs: string; checkpointId: string };
    };

    /** Where the case came from. (threadId, checkpointId) is the dedupe key. */
    source: {
        department: "orchestrator" | "distribution-dep" | "curriculum-dep" | "signal-editor-dep";
        threadId: string;
        checkpointId: string;
        opikTraceId?: string;
        capturedAt: string; // ISO timestamp
    };

    /** Rendered steps from loadThreadTranscript; what the evolution run reads to find the failure. */
    transcript: string;
    skillsRead: string[];
    stats: Transcript["stats"];

    /** Why it was added. `reason` is also the seed for the item's assertions. */
    judge: { name: string; model: string; score: number; threshold: number; reason: string };
}

export const skillEvalSuiteName = (agent: string) => `${agent}_skill_evals`;

export function buildSkillEvalItem(args: {
    agent: string;
    department: SkillEvalItemData["source"]["department"];
    transcript: Transcript;
    input: string;
    judge: SkillEvalItemData["judge"];
    /** Concrete, checkable statements about correct behaviour; must be specific to this case. */
    assertions: string[];
    description?: string;
    opikTraceId?: string;
    /** Replay from the stored checkpoint rather than from `input` alone. */
    resume?: boolean;
}): TestSuiteItem {
    const { transcript: t } = args;
    const data: SkillEvalItemData = {
        schemaVersion: 1,
        agent: args.agent,
        replay: {
            input: args.input,
            ...(args.resume ? { resumeFrom: { threadId: t.threadId, checkpointNs: t.checkpointNs, checkpointId: t.checkpointId } } : {}),
        },
        source: {
            department: args.department,
            threadId: t.threadId,
            checkpointId: t.checkpointId,
            ...(args.opikTraceId ? { opikTraceId: args.opikTraceId } : {}),
            capturedAt: new Date().toISOString(),
        },
        transcript: t.text,
        skillsRead: t.skillsRead,
        stats: t.stats,
        judge: args.judge,
    };
    return {
        data: data as unknown as Record<string, unknown>,
        assertions: args.assertions,
        description: args.description ?? args.judge.reason.slice(0, 200),
    };
}

/** True when a suite already holds this checkpoint; call before insert so re-runs don't duplicate cases. */
export function hasCase(items: Array<{ data: Record<string, unknown> }>, threadId: string, checkpointId: string): boolean {
    return items.some((i) => {
        const s = (i.data as Partial<SkillEvalItemData>).source;
        return s?.threadId === threadId && s?.checkpointId === checkpointId;
    });
}
