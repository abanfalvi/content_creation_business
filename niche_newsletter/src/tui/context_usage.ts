import { AIMessage, type BaseMessage } from "@langchain/core/messages";

const DEFAULT_CONTEXT_WINDOW = 200_000;
const MODELS_URL = "https://openrouter.ai/api/v1/models";

// Context window of an OpenRouter model; NL_CONTEXT_WINDOW overrides, and any lookup failure falls back to a default.
export async function fetchContextWindow(model: string): Promise<number> {
    const override = Number(process.env.NL_CONTEXT_WINDOW);
    if (override > 0) return override;
    try {
        const response = await fetch(MODELS_URL, { signal: AbortSignal.timeout(5000) });
        const body = (await response.json()) as { data?: { id: string; context_length?: number }[] };
        return body.data?.find((m) => m.id === model)?.context_length || DEFAULT_CONTEXT_WINDOW;
    } catch {
        return DEFAULT_CONTEXT_WINDOW;
    }
}

const textLength = (message: BaseMessage) =>
    typeof message.content === "string" ? message.content.length : JSON.stringify(message.content).length;

// Tokens currently in the conversation: the provider-reported total of the latest model
// response (prompt + completion = what the next call will start from), else a ~4 chars/token estimate.
export function countContextTokens(messages: BaseMessage[]): number {
    const last = [...messages].reverse().find((m): m is AIMessage => AIMessage.isInstance(m));
    const reported = (last?.usage_metadata as { total_tokens?: number } | undefined)?.total_tokens;
    if (last && reported) {
        const afterIdx = messages.lastIndexOf(last) + 1;
        return reported + messages.slice(afterIdx).reduce((sum, m) => sum + Math.ceil(textLength(m) / 4), 0);
    }
    return Math.ceil(messages.reduce((sum, m) => sum + textLength(m), 0) / 4);
}
