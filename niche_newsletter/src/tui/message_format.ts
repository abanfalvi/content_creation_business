import type { BaseMessage } from "@langchain/core/messages";

export type ChatRole = "user" | "assistant" | "tool" | "status" | "error";
export type ChatEntryDraft = { role: ChatRole; text: string };

const TOOL_RESULT_PREVIEW_LENGTH = 400;

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
        const type = message.getType();

        if (type === "ai") {
            const toolCalls = (message as unknown as { tool_calls?: Array<{ name: string; args: unknown }> }).tool_calls;
            for (const call of toolCalls ?? []) {
                entries.push({ role: "status", text: `→ calling ${call.name}(${JSON.stringify(call.args)})` });
            }
            const text = contentToText(message.content).trim();
            if (text) entries.push({ role: "assistant", text });
        } else if (type === "tool") {
            const name = (message as unknown as { name?: string }).name;
            const text = contentToText(message.content).trim();
            const preview = text.length > TOOL_RESULT_PREVIEW_LENGTH
                ? `${text.slice(0, TOOL_RESULT_PREVIEW_LENGTH)}…`
                : text;
            entries.push({ role: "tool", text: `${name ? `${name} → ` : ""}${preview}` });
        } else if (type === "human") {
            const text = contentToText(message.content).trim();
            if (text) entries.push({ role: "user", text });
        }
    }

    return entries;
}
