import { researchAgent } from "./signal-editor-dep/research_agent/agent.js";
import { relFilterAgent } from "./signal-editor-dep/rel_filter_agent/agent.js";
import { editorAgent } from "./signal-editor-dep/editor_agent/agent.js";
import {opikHandler} from "./models.js";
import {HumanMessage} from "@langchain/core/messages";

try {
    const result = await editorAgent.invoke(
        {
            messages: [new HumanMessage(`What tools from Notion are available to you? Collect their names and brief descriptions`)],
            researchTopic: "ai_marketing_automation"
        },
        { callbacks: [opikHandler], recursionLimit: 30 }
    );
    console.log(result.messages.at(-1)?.content);
} catch (error) {
    console.log(error)
}


await opikHandler.flushAsync();