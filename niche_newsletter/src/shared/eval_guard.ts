import { tool, type DynamicStructuredTool } from "@langchain/core/tools";

// Active only when the eval harness sets EVAL_MODE=1 before importing any agent.
// Write tools matching `writePattern` are swapped for recorders so an eval run
// can't publish, email subscribers, or modify real posts/pages.

export type SideEffect = { server: string; tool: string; args: unknown; at: string };

export const sideEffectLog: SideEffect[] = [];

let mockCounter = 0;

export function isEvalMode(): boolean {
    return process.env.EVAL_MODE === "1";
}

export function guardWriteTools(server: string, tools: DynamicStructuredTool[], writePattern: RegExp): DynamicStructuredTool[] {
    if (!isEvalMode()) return tools;

    return tools.map((original) => {
        if (!writePattern.test(original.name)) return original;

        return tool(
            async (args: unknown) => {
                mockCounter += 1;
                sideEffectLog.push({ server, tool: original.name, args, at: new Date().toISOString() });
                return JSON.stringify({ success: true, id: `eval-mock-${mockCounter}` });
            },
            {
                name: original.name,
                description: original.description,
                schema: original.schema,
            },
        ) as unknown as DynamicStructuredTool;
    });
}

export const BEEHIIV_WRITE_TOOLS = /^(save|edit|duplicate|update|delete|create)_/;
export const NOTION_WRITE_TOOLS = /^notion-(create|update|move|duplicate|convert)/;
export const BUFFER_WRITE_TOOLS = /^(create|edit|update|delete)_/;
