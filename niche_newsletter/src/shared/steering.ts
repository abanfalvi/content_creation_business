import { createMiddleware, HumanMessage, type AnyAgentMiddleware } from "langchain";

// Steering text typed in the TUI while a run is going. Keyed by target: the orchestrator's
// thread id, or the name a sub-agent was started under (streamAgents' `name`). Everything runs
// in one process and push/drain are synchronous, so no locking is needed.
const boxes = new Map<string, string[]>();

export const steeringMailbox = {
  push: (target: string, text: string) => {
    const pending = boxes.get(target);
    if (pending) pending.push(text);
    else boxes.set(target, [text]);
  },
  // Takes (and clears) everything addressed to any of `keys`.
  drain: (keys: (string | undefined)[]) => {
    const texts: string[] = [];
    for (const key of keys) {
      if (!key) continue;
      const pending = boxes.get(key);
      if (!pending) continue;
      texts.push(...pending);
      boxes.delete(key);
    }
    return texts.join("\n\n");
  },
  // Whatever nobody picked up (the target finished first).
  takeAll: () => {
    const rest = [...boxes].flatMap(([target, texts]) => texts.map((text) => ({ target, text })));
    boxes.clear();
    return rest;
  },
};

// Appended to every steerable agent's system prompt (one copy here instead of one per prompt file).
export const STEERING_PROMPT = `

## Live user steering
The user can send you new direction while you work. It arrives as a message wrapped in <user_steering> tags, between two of your steps. It comes straight from the user and takes priority over your earlier instructions and over your plan: acknowledge it by acting on it, drop or adjust whatever it contradicts, and keep the parts of your task it doesn't touch. Don't repeat work you've already finished unless the steering asks for it. If it makes your current task impossible or unclear, say so in your final answer instead of ignoring it.`;

export const steeringMiddleware = createMiddleware({
  name: "steering_messages_middleware",
  
  beforeModel: (_state, runtime) => {
    const agentName = runtime.configurable?.agent_name as string | undefined;
    const text = steeringMailbox.drain([runtime.configurable?.thread_id as string | undefined, agentName]);
    if (!text) return {};
    // Sub-agent messages never reach the TUI's orchestrator stream, so announce them. The
    // orchestrator's own steering shows up through its message stream.
    if (agentName) runtime.writer?.({ type: "steered", agent: agentName, path: [agentName], text });
    return {
      messages: [new HumanMessage({
        content: `<user_steering>\n${text}\n</user_steering>`,
        additional_kwargs: { lc_source: "user_steering" },
      })],
    };
  },
}) as AnyAgentMiddleware;
