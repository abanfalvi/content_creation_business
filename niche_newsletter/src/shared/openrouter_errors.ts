import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { trackResponseCost } from "./cost_tracker.js";

// OpenRouter sometimes answers HTTP 200 with an error body instead of a completion (the
// upstream provider failed after the request was accepted):
//   { "error": { "message": "...", "code": 502, "metadata": { "provider_name": "...", "raw": ... } } }
// @langchain/openrouter only checks the status code, then crashes on `data.choices[0]`
// with "Cannot read properties of undefined (reading '0')", and the real reason is lost.
//
// This wraps the global fetch (which @langchain/openrouter calls directly) so such
// responses are logged in full and surfaced as an error carrying OpenRouter's message.

const LOG_PATH = join(process.env.DATA_ROOT ?? ".", "logs", "openrouter_errors.jsonl");

export class OpenRouterProviderError extends Error {
    override name = "OpenRouterProviderError";
}

type ErrorBody = { error?: { message?: string; code?: number | string; metadata?: { provider_name?: string; raw?: unknown } } };

function describe(body: ErrorBody, model: string | undefined): string {
    const error = body.error;
    const provider = error?.metadata?.provider_name;
    const raw = error?.metadata?.raw;
    return [
        `OpenRouter returned no completion for ${model ?? "unknown model"}`,
        provider && `(provider: ${provider})`,
        `— ${error?.message ?? "no error message in response"}`,
        error?.code !== undefined && `[code ${error.code}]`,
        raw !== undefined && `raw: ${typeof raw === "string" ? raw : JSON.stringify(raw)}`.slice(0, 500),
    ].filter(Boolean).join(" ");
}

function log(entry: object) {
    try {
        mkdirSync(dirname(LOG_PATH), { recursive: true });
        appendFileSync(LOG_PATH, `${JSON.stringify({ time: new Date().toISOString(), ...entry })}\n`);
    } catch {
        // Logging must never break a model call.
    }
}

let installed = false;

export function installOpenRouterErrorCapture() {
    if (installed) return;
    installed = true;
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async (input, init) => {
        const response = await originalFetch(input, init);
        const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        const isCompletion = url.includes("openrouter.ai") && url.includes("/chat/completions");
        const isJson = response.headers.get("content-type")?.includes("application/json");
        if (isCompletion && response.ok) void trackResponseCost(response.clone(), !!isJson);
        if (!isCompletion || !response.ok || !isJson) return response;

        // Read a clone so the caller can still consume the original body.
        const body = await response.clone().json().catch(() => undefined) as (ErrorBody & { choices?: unknown[] }) | undefined;
        if (!body || (Array.isArray(body.choices) && body.choices.length > 0)) return response;

        let model: string | undefined;
        try { model = JSON.parse(String(init?.body ?? "{}")).model; } catch { /* body isn't JSON */ }
        const message = describe(body, model);
        log({ model, message, response: body });
        throw new OpenRouterProviderError(message);
    };
}
