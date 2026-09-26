import { type BaseMessage, HumanMessage } from "langchain";
import { memoryManageAgent } from "../memory_agent/agent.js";

export async function saveIntoMemories(descriptions: string[], messages: BaseMessage[] ) {
    const transcript = messages
        .map(m => `${m.type}: ${typeof m.content === "string" ? m.content : JSON.stringify(m.content)}`)
        .join("\n");
    const result = await memoryManageAgent.invoke({
        messages: [new HumanMessage({content: `Save the described informations (${descriptions.join("\n")}) from this list of messages from the executions of an agent: ${transcript}`})]
    });

    return result.messages.at(-1)?.content
};