import { researchAgent } from "./signal-editor-dep/research_agent/agent.js";
import { relFilterAgent } from "./signal-editor-dep/rel_filter_agent/agent.js";
import { editorAgent } from "./signal-editor-dep/editor_agent/agent.js";
import { SMAgent } from "./distribution-dep/sm_agent/agent.js";
import { OutreachAgent } from "./distribution-dep/user_outreach_agent/agent.js";
import {opikHandler} from "./models.js";
import {HumanMessage} from "@langchain/core/messages";

try {
    const result = await OutreachAgent.invoke(
        {
            messages: [new HumanMessage(`Find out what Actors on Apify can help to find potential leads for a newsletter agency on Instagram.`)],
            // researchTopic: "ai_marketing_automation"
        },
        { callbacks: [opikHandler], recursionLimit: 30 }
    );
    console.log(result.messages.at(-1)?.content);
} catch (error) {
    console.log(error)
}


await opikHandler.flushAsync();