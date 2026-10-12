import type { ReactAgent, ToolRuntime } from "langchain";

export type ProgressEvent =
  | { type: "agent_start"; agent: string; path: string[] }
  | { type: "tool_call";   agent: string; path: string[]; name: string; args: unknown }
  | { type: "agent_end";   agent: string; path: string[] }
  | { type: "steered";     agent: string; path: string[]; text: string };

export async function streamAgents<A extends ReactAgent<any>>(agent: A, name: string, input: Parameters<A["stream"]>[0], threadId: string, runtime: ToolRuntime, agentContext: Record<string, unknown> = {}) {
    const path = [name];
    runtime.writer?.({ type: "agent_start", agent: name, path });

    let final: Awaited<ReturnType<A["invoke"]>> | undefined;
    try {
        for await (const [mode, chunk] of await agent.stream(input, {
            streamMode: ["updates", "values", "custom"],
            // agent_name is the address /steer @<name> delivers to (see steering.ts).
            configurable: { thread_id: threadId, agent_name: name },
            context: agentContext,
            signal: runtime.config?.signal!, 
        })) {
            if (mode === "custom") { 
                const event = chunk as ProgressEvent;
                runtime.writer?.({...event, path: [name, ...event.path] });
                continue; 
            }
            if (mode === "values") {
                final = chunk as typeof final;
                continue;
            }
            for (const msg of Object.values(chunk).flatMap((u: any) => u?.messages ?? [])) {
                for (const tc of msg.tool_calls ?? [])
                    runtime.writer?.({ type: "tool_call", agent: name, path, name: tc.name, args: tc.args });
            }
        }
    } finally {
        // Also on failure/cancel, so listeners tracking running agents don't keep a dead one.
        runtime.writer?.({ type: "agent_end", agent: name, path });
    }
    if (!final) throw new Error(`${name} produced no output`);
    
    return final

};