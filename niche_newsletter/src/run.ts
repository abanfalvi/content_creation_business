import { researchAgent } from "./signal-editor-dep/research_agent/agent.js";
import {opikHandler} from "./models.js";
import {HumanMessage} from "@langchain/core/messages";

try {
    const result = await researchAgent.invoke(
        {
            messages: [new HumanMessage(`Collect the most recommended AI automation techniques for marketers. Current date: ${new Date().toDateString()}`)],
        },
        { callbacks: [opikHandler], recursionLimit: 100 }
    );
    console.log(result.messages.at(-1)?.content);
} catch (error) {
    console.log(error)
}


await opikHandler.flushAsync();