import { researchAgent } from "./signal-editor-dep/research_agent/agent.js";
import {opikHandler} from "./models.js";
import {HumanMessage} from "@langchain/core/messages";

const result = await researchAgent.invoke(
    {
        messages: [new HumanMessage(`What are the most recent LLM releases and what did they introduce? Current date: ${new Date()}`)],
    },
    { callbacks: [opikHandler], recursionLimit: 30 }
);

console.log(result.messages.at(-1)?.content);
await opikHandler.flushAsync();