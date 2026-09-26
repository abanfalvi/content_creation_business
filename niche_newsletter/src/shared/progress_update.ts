import type { ReactAgent, ToolRuntime } from "langchain";

export type ProgressEvent =
  | { type: "agent_start"; agent: string; path: string[] }
  | { type: "tool_call";   agent: string; path: string[]; name: string; args: unknown }
  | { type: "agent_end";   agent: string; path: string[] };

export async function streamAgents<A extends ReactAgent<any>>(agent: A, name: string, input: Parameters<A["stream"]>[0], threadId: string, runtime: ToolRuntime) {
    const path = [name];
    runtime.writer?.({ type: "agent_start", agent: name, path });

    let final: Awaited<ReturnType<A["invoke"]>> | undefined;
    for await (const [mode, chunk] of await agent.stream(input, {
        streamMode: ["updates", "values", "custom"],
        configurable: { thread_id: threadId }
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
    runtime.writer?.({ type: "agent_end", agent: name, path });
    if (!final) throw new Error(`${name} produced no output`);
    
    return final

};