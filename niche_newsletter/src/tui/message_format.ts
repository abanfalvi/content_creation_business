import type { BaseMessage } from "@langchain/core/messages";
import type { ProgressEvent } from "../shared/progress_update.js";

export type ChatRole = "user" | "assistant" | "tool" | "status" | "error";
export type ChatEntryDraft = { role: ChatRole; text: string; depth?: number; agent?: string };

const TOOL_ARGS_PREVIEW_LENGTH = 120;

export function contentToText(content: unknown): string {
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
        return content
            .map((block) => {
                if (typeof block === "string") return block;
                if (block && typeof block === "object" && "text" in block && typeof (block as { text: unknown }).text === "string") {
                    return (block as { text: string }).text;
                }
                return "";
            })
            .filter(Boolean)
            .join("\n");
    }
    if (content == null) return "";
    return JSON.stringify(content);
}

export function messagesToEntries(messages: BaseMessage[]): ChatEntryDraft[] {
    const entries: ChatEntryDraft[] = [];

    for (const message of messages) {
        const type = message.type;

        if (type === "ai") {
            const toolCalls = (message as unknown as { tool_calls?: Array<{ name: string; args: unknown }> }).tool_calls;
            for (const call of toolCalls ?? []) {
                const args = JSON.stringify(call.args) ?? "";
                const preview = args.length > TOOL_ARGS_PREVIEW_LENGTH ? `${args.slice(0, TOOL_ARGS_PREVIEW_LENGTH)}…` : args;
                entries.push({ role: "status", text: `→ calling ${call.name}(${preview})` });
            }
            const text = contentToText(message.content).trim();
            if (text) entries.push({ role: "assistant", text });
        } else if (type === "human") {
            const text = contentToText(message.content).trim();
            if (text) entries.push({ role: "user", text });
        }
    }

    return entries;
}

export function progressEventToEntry(event: ProgressEvent): ChatEntryDraft {
    const base = { depth: event.path.length, agent: event.agent };
    switch (event.type) {
        case "agent_start": return { ...base, role: "status", text: `▶ ${event.agent} started` };
        case "agent_end": return { ...base, role: "status", text: `■ ${event.agent} finished` };
        case "tool_call": {
            const args = JSON.stringify(event.args) ?? "";
            const preview = args.length > TOOL_ARGS_PREVIEW_LENGTH ? `${args.slice(0, TOOL_ARGS_PREVIEW_LENGTH)}…` : args;
            return { ...base, role: "tool", text: `→ ${event.name}(${preview})` };
        }
    }
}
