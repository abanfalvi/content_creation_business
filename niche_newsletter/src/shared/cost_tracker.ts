// Running total of what OpenRouter charged for this process's model calls (sub-agents included),
// read from the `usage.cost` field of each chat completion response.

let total = 0;
const listeners = new Set<(total: number) => void>();

export const getTotalCost = () => total;

export function onCostChange(listener: (total: number) => void) {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
}

function addCost(cost: unknown) {
    if (typeof cost !== "number" || !(cost > 0)) return;
    total += cost;
    listeners.forEach((l) => l(total));
}

type Usage = { usage?: { cost?: number } };

// Reads a clone of a completion response (JSON or SSE stream) and records its cost.
export async function trackResponseCost(clone: Response, isJson: boolean) {
    try {
        const text = await clone.text();
        if (isJson) {
            addCost((JSON.parse(text) as Usage).usage?.cost);
            return;
        }
        // Streaming: only the final chunk carries `usage`.
        for (const line of text.split("\n")) {
            if (!line.startsWith("data:") || !line.includes('"cost"')) continue;
            addCost((JSON.parse(line.slice(5)) as Usage).usage?.cost);
        }
    } catch {
        // Cost display must never break a model call.
    }
}
