import type { BaseMessage } from "@langchain/core/messages";
import type { BaseCheckpointSaver } from "@langchain/langgraph-checkpoint";

export interface TranscriptToolCall {
    id: string;
    name: string;
    args: unknown;
    /** Undefined when no matching ToolMessage was found (run cut off, or result lives elsewhere). */
    result?: { status: "success" | "error"; text: string };
}

export interface TranscriptStep {
    /** 1-based position in the message list. */
    index: number;
    role: "user" | "agent" | "system";
    text: string;
    toolCalls: TranscriptToolCall[];
}

export interface Transcript {
    threadId: string;
    checkpointId: string;
    checkpointNs: string;
    steps: TranscriptStep[];
    /** First human message, unclipped: the task the agent was given. */
    input: string;
    /** Skill names whose SKILL.md was read, in order of first read. */
    skillsRead: string[];
    stats: { steps: number; toolCalls: number; toolErrors: number };
    /** Judge-/analyst-readable rendering of `steps`. */
    text: string;
}

export interface TranscriptOptions {
    /** Max chars kept from each tool result (head + tail). */
    maxResultChars?: number;
    /** Max chars kept from each tool call's JSON args. */
    maxArgsChars?: number;
    /** Max chars kept from each human/agent message. */
    maxTextChars?: number;
}

const DEFAULTS: Required<TranscriptOptions> = { maxResultChars: 600, maxArgsChars: 300, maxTextChars: 20000 };

const SKILL_PATH = /\/skills\/([^/]+)\/SKILL\.md/;

function clip(s: string, max: number): string {
    if (s.length <= max) return s;
    const head = Math.ceil(max * 0.7);
    const tail = max - head;
    return `${s.slice(0, head)} …[${s.length - max} chars omitted]… ${s.slice(s.length - tail)}`;
}

/** Message content is either a string or an array of blocks; keep only the text. */
function contentToText(content: unknown): string {
    if (typeof content === "string") return content;
    if (!Array.isArray(content)) return content == null ? "" : JSON.stringify(content);
    return content
        .map((block) => {
            if (typeof block === "string") return block;
            if (block && typeof block === "object" && (block as { type?: string }).type === "text") {
                return String((block as { text?: unknown }).text ?? "");
            }
            return "";
        })
        .filter(Boolean)
        .join("\n");
}

function roleOf(m: BaseMessage): "user" | "agent" | "tool" | "system" {
    const t = typeof m.getType === "function" ? m.getType() : (m as { type?: string }).type;
    if (t === "human") return "user";
    if (t === "ai") return "agent";
    if (t === "tool") return "tool";
    return "system";
}

/** Pure: turns an ordered message list into structured steps, pairing each tool call with its result. */
export function buildSteps(messages: BaseMessage[], options: TranscriptOptions = {}): TranscriptStep[] {
    const opt = { ...DEFAULTS, ...options };
    const steps: TranscriptStep[] = [];
    const callsById = new Map<string, TranscriptToolCall>();

    messages.forEach((m, i) => {
        const role = roleOf(m);

        if (role === "tool") {
            const tm = m as BaseMessage & { tool_call_id?: string; status?: string; name?: string };
            const full = contentToText(m.content);
            // The file tools return failures as ordinary results ("Error: ..."), so status alone misses them.
            const result = {
                status: tm.status === "error" || /^\s*Error\b/.test(full) ? ("error" as const) : ("success" as const),
                text: clip(full, opt.maxResultChars),
            };
            const call = tm.tool_call_id ? callsById.get(tm.tool_call_id) : undefined;
            if (call) {
                call.result = result;
            } else {
                // Result with no preceding call in this window; keep it visible rather than dropping it.
                steps.push({
                    index: i + 1,
                    role: "agent",
                    text: "",
                    toolCalls: [{ id: tm.tool_call_id ?? "", name: tm.name ?? "unknown", args: undefined, result }],
                });
            }
            return;
        }

        const toolCalls: TranscriptToolCall[] =
            role === "agent"
                ? ((m as BaseMessage & { tool_calls?: { id?: string; name: string; args: unknown }[] }).tool_calls ?? []).map((tc) => ({
                      id: tc.id ?? "",
                      name: tc.name,
                      args: tc.args,
                  }))
                : [];
        for (const tc of toolCalls) if (tc.id) callsById.set(tc.id, tc);

        steps.push({ index: i + 1, role: role === "agent" ? "agent" : role, text: clip(contentToText(m.content), opt.maxTextChars), toolCalls });
    });

    return steps;
}

export function renderSteps(steps: TranscriptStep[], options: TranscriptOptions = {}): string {
    const opt = { ...DEFAULTS, ...options };
    const lines: string[] = [];
    for (const s of steps) {
        const label = s.role === "user" ? "USER" : s.role === "agent" ? "AGENT" : "SYSTEM";
        if (s.text) lines.push(`[${s.index}] ${label}: ${s.text}`);
        else if (s.toolCalls.length === 0) lines.push(`[${s.index}] ${label}: (empty)`);
        else lines.push(`[${s.index}] ${label}:`);
        for (const tc of s.toolCalls) {
            const args = tc.args === undefined ? "" : clip(JSON.stringify(tc.args), opt.maxArgsChars);
            lines.push(`    -> ${tc.name}(${args})`);
            if (tc.result) lines.push(`       <- ${tc.result.status === "error" ? "ERROR" : "ok"}: ${tc.result.text}`);
            else lines.push(`       <- (no result recorded)`);
        }
    }
    return lines.join("\n");
}

function skillsReadFrom(steps: TranscriptStep[]): string[] {
    const seen = new Set<string>();
    for (const s of steps) {
        for (const tc of s.toolCalls) {
            const path = (tc.args as { file_path?: unknown } | undefined)?.file_path;
            const name = typeof path === "string" ? SKILL_PATH.exec(path)?.[1] : undefined;
            if (name) seen.add(name);
        }
    }
    return [...seen];
}

/**
 * Loads the latest (or a specific) checkpoint of a thread and renders it as a step-by-step transcript.
 * Returns undefined when the thread/checkpoint does not exist.
 */
export async function loadThreadTranscript(
    checkpointer: BaseCheckpointSaver,
    threadId: string,
    opts: { checkpointId?: string; checkpointNs?: string } & TranscriptOptions = {},
): Promise<Transcript | undefined> {
    const { checkpointId, checkpointNs = "", ...render } = opts;
    const tuple = await checkpointer.getTuple({
        configurable: { thread_id: threadId, checkpoint_ns: checkpointNs, ...(checkpointId ? { checkpoint_id: checkpointId } : {}) },
    });
    if (!tuple) return undefined;

    const messages = ((tuple.checkpoint.channel_values as { messages?: BaseMessage[] }).messages ?? []);
    return transcriptFromMessages(messages, {
        threadId,
        checkpointId: String(tuple.config.configurable?.checkpoint_id ?? ""),
        checkpointNs,
        ...render,
    });
}

/** Same output as loadThreadTranscript, for messages you already hold (e.g. a fresh eval run's result.messages). */
export function transcriptFromMessages(
    messages: BaseMessage[],
    meta: { threadId: string; checkpointId: string; checkpointNs?: string } & TranscriptOptions,
): Transcript {
    const { threadId, checkpointId, checkpointNs = "", ...render } = meta;
    const steps = buildSteps(messages, render);
    const calls = steps.flatMap((s) => s.toolCalls);
    const firstUser = messages.find((m) => roleOf(m) === "user");
    return {
        threadId,
        checkpointId,
        checkpointNs,
        steps,
        input: firstUser ? contentToText(firstUser.content) : "",
        skillsRead: skillsReadFrom(steps),
        stats: { steps: steps.length, toolCalls: calls.length, toolErrors: calls.filter((c) => c.result?.status === "error").length },
        text: renderSteps(steps, render),
    };
}
