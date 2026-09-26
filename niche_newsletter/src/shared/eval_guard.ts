import { tool, type DynamicStructuredTool } from "@langchain/core/tools";

// Active only when the eval harness sets EVAL_MODE=1 before importing any agent.
// Write tools matching `writePattern` are swapped for recorders so an eval run
// can't publish, email subscribers, or modify real posts/pages.

export type SideEffect = { server: string; tool: string; args: unknown; at: string };

export const sideEffectLog: SideEffect[] = [];

export type GuardOptions = {
    // Prefix for mock IDs, so they look like the server's own (e.g. "post_" for beehiiv).
    idPrefix?: string;
    // Read tools that must not hit the real server when given a mock ID: the object only
    // exists in the recorder, so they answer from the recorded writes instead.
    mockReads?: RegExp;
};

type MockObject = { created_by: { tool: string; args: unknown }; later_writes: { tool: string; args: unknown }[] };

const MOCK_MARKER = "eval-mock-";
const mockObjects = new Map<string, MockObject>();
let mockCounter = 0;

export function isEvalMode(): boolean {
    return process.env.EVAL_MODE === "1";
}

// The first string argument that is a mock ID, e.g. post_id on edit_post_content.
function findMockId(args: unknown): string | undefined {
    if (args === null || typeof args !== "object") return undefined;
    return Object.values(args).find((value): value is string => typeof value === "string" && mockObjects.has(value));
}

export function guardWriteTools(server: string, tools: DynamicStructuredTool[], writePattern: RegExp, options: GuardOptions = {}): DynamicStructuredTool[] {
    if (!isEvalMode()) return tools;
    const { idPrefix = "", mockReads } = options;

    return tools.map((original) => {
        if (writePattern.test(original.name)) {
            return tool(
                async (args: unknown) => {
                    sideEffectLog.push({ server, tool: original.name, args, at: new Date().toISOString() });
                    // A write to an object created earlier in this run keeps its ID.
                    const existingId = findMockId(args);
                    if (existingId) {
                        mockObjects.get(existingId)!.later_writes.push({ tool: original.name, args });
                        return JSON.stringify({ success: true, id: existingId });
                    }
                    mockCounter += 1;
                    const id = `${idPrefix}${MOCK_MARKER}${mockCounter}`;
                    mockObjects.set(id, { created_by: { tool: original.name, args }, later_writes: [] });
                    return JSON.stringify({ success: true, id });
                },
                { name: original.name, description: original.description, schema: original.schema },
            ) as unknown as DynamicStructuredTool;
        }

        if (mockReads?.test(original.name)) {
            return tool(
                async (args: unknown) => {
                    const mockId = findMockId(args);
                    if (!mockId) return original.invoke(args as Record<string, unknown>);
                    return JSON.stringify({
                        id: mockId,
                        note: "Eval run: this object was only recorded, never sent to the server. Its content is the creating call's arguments with the later writes applied on top, in order.",
                        ...mockObjects.get(mockId),
                    });
                },
                { name: original.name, description: original.description, schema: original.schema },
            ) as unknown as DynamicStructuredTool;
        }

        return original;
    });
}

export const BEEHIIV_WRITE_TOOLS = /^(save|edit|duplicate|update|delete|create)_/;
export const BEEHIIV_MOCK_READS = /^get_post/;
export const NOTION_WRITE_TOOLS = /^notion-(create|update|move|duplicate|convert)/;
export const BUFFER_WRITE_TOOLS = /^(create|edit|update|delete)_/;
