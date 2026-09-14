import { researchAgent } from "./signal-editor-dep/research_agent/agent.js";
import { relFilterAgent } from "./signal-editor-dep/rel_filter_agent/agent.js";
import {opikHandler} from "./models.js";
import {HumanMessage} from "@langchain/core/messages";

try {
    const result = await relFilterAgent.invoke(
        {
            messages: [new HumanMessage(`Trim what is relevant from the research findings. Current research topic: AI marketing automation techniques. Current date: ${new Date().toDateString()}`)],
            researchTopic: "ai_marketing_automation"
        },
        { callbacks: [opikHandler], recursionLimit: 100 }
    );
    console.log(result.messages.at(-1)?.content);
} catch (error) {
    console.log(error)
}


await opikHandler.flushAsync();