// Capabilities: call other agents, review newsletter using rubric
import { tool, type ToolRuntime } from "@langchain/core/tools";
import { HumanMessage, ToolMessage } from "@langchain/core/messages";
import { Command } from "@langchain/langgraph";
import { type AgentStateType, newsletterRubric } from "./state.js";
import type { NewsletterRubricType } from "./state.js";
import { getNotionMCP } from "../../shared/notion_mcp.js";
import { getBeehiivMCP } from "../../shared/beehiiv_mcp.js";
import { streamAgents } from "../../shared/progress_update.js";

type handoffContract = {
    task_id: string;
    objectives: string[];
    constraints: string[];
    deliverables: string[];
};

const PASSING_SCORE = 5;

const KEEP_BEEHIIV_TOOLS = new Set([
    "get_post",
    "get_post_content",
    "get_post_footer",
    "list_posts",
    // Referral program management — creating/editing milestones, rewards, and program
    // settings. Reading how the program is performing is the orchestrator's job, not
    // this agent's; it only needs get_referral_program as a prerequisite read before
    // save_referral_program/save_referral_milestone (both require current settings).
    "get_referral_program",
    "list_referral_rewards",
    "save_referral_reward",
    "save_referral_milestone",
    "save_referral_program",
])

function lastMessageContent(result: { messages: { content: unknown }[] }): string {
    const last = result.messages.at(-1);
    return typeof last?.content === "string" ? last.content : JSON.stringify(last?.content ?? "");
}

const callEditorAgent = tool(
    async (instruction: handoffContract, runtime: ToolRuntime<AgentStateType>) => {
        const managerThreadId = runtime.config.configurable?.thread_id as string | undefined
        const { editorAgent } = await import("../editor_agent/agent.js");
        const topic = runtime.state.researchTopic
        const threadId = `${managerThreadId ?? "unknown"}:editor_agent`;
        const result = await streamAgents(
            editorAgent, 
            "editor_agent",
            {messages: [new HumanMessage({content: JSON.stringify(instruction)})], researchTopic: topic},
            threadId,
            runtime
        );
        return result.messages.at(-1)?.content
    }, {
        name: "call_editor_agent",
        description: "Call the newsletter editor agent to write a newsletter post",
    }
);

const callRelevanceFilterAgent = tool(
    async (instruction: handoffContract, runtime: ToolRuntime<AgentStateType>) => {
        const managerThreadId = runtime.config.configurable?.thread_id as string | undefined
        const { relFilterAgent } = await import("../rel_filter_agent/agent.js");
        const topic = runtime.state.researchTopic
        const threadId = `${managerThreadId ?? "unknown"}:rel_filter_agent`;
        const result = await streamAgents(
            relFilterAgent, 
            "relevance_filter_agent",
            {messages: [new HumanMessage({content: JSON.stringify(instruction)})], researchTopic: topic},
            threadId,
            runtime
        );
        if (runtime.state.currentStep === "flexibleWorkflow") return result.messages.at(-1)?.content
        return new Command({
            update: {
                messages: [new ToolMessage({content: lastMessageContent(result), tool_call_id: runtime.toolCallId})],
                currentStep: "useCaseStep"
            }
        });
    }, {
        name: "call_rel_filter_agent",
        description: "Call the relevance filter agent to trim down the research findings to the most relevant ones for the editor agent",
    }
);

const callResearchAgent = tool(
    async (instruction: handoffContract, runtime: ToolRuntime<AgentStateType>) => {
        const managerThreadId = runtime.config.configurable?.thread_id as string | undefined
        const { researchAgent } = await import("../research_agent/agent.js");
        const topic = runtime.state.researchTopic
        const threadId = `${managerThreadId ?? "unknown"}:research_agent`;
        const result = await streamAgents(
            researchAgent, 
            "research_agent",
            {messages: [new HumanMessage({content: JSON.stringify(instruction)})], researchTopic: topic},
            threadId,
            runtime
        );
        if (runtime.state.currentStep === "flexibleWorkflow") return result.messages.at(-1)?.content
        return new Command({
            update: {
                messages: [new ToolMessage({content: lastMessageContent(result), tool_call_id: runtime.toolCallId})],
                currentStep: "filteringStep"
            }
        });
    }, {
        name: "call_research_agent",
        description: "Call the research agent to conduct extensive research on a given topic",
    }
);

const callUseCaseWriterAgent = tool(
    async (instruction: handoffContract, runtime: ToolRuntime<AgentStateType>) => {
        const managerThreadId = runtime.config.configurable?.thread_id as string | undefined
        const { userCaseWriterAgent } = await import("../use_case_writer_agent/agent.js");
        const topic = runtime.state.researchTopic
        const threadId = `${managerThreadId ?? "unknown"}:use_case_writer_agent`;
        const result = await streamAgents(
            userCaseWriterAgent, 
            "use_case_writer_agent",
            {messages: [new HumanMessage({content: JSON.stringify(instruction)})], researchTopic: topic},
            threadId,
            runtime
        );
        if (runtime.state.currentStep === "flexibleWorkflow") return result.messages.at(-1)?.content
        return new Command({
            update: {
                messages: [new ToolMessage({content: lastMessageContent(result), tool_call_id: runtime.toolCallId})],
                currentStep: "editingStep"
            }
        });
    }, {
        name: "call_use_case_writer_agent",
        description: "Call the use case writer agent to turn use case examples from the research finding into practical use cases for the readers",
    }
);

const reviewNewsletter = tool(
    async (rubric: NewsletterRubricType) => {
        const total = rubric.structure + rubric.visualRelevance + rubric.groundedness;
        const passed = rubric.formatCorrect && total >= PASSING_SCORE;

        if (passed) {
            return `Approved — score ${total}/6, format correct. Ready for human review and publish in beehiiv.`;
        }

        const issues: string[] = [];
        if (!rubric.formatCorrect) issues.push(`Format (disqualifying): ${rubric.formatCorrectEvidence}`);
        if (rubric.structure < 2) issues.push(`Structure (${rubric.structure}/2): ${rubric.structureEvidence}`);
        if (rubric.visualRelevance < 2) issues.push(`Visuals (${rubric.visualRelevance}/2): ${rubric.visualRelevanceEvidence}`);
        if (rubric.groundedness < 2) issues.push(`Groundedness (${rubric.groundedness}/2): ${rubric.groundednessEvidence}`);

        return `Needs revision — score ${total}/6. Turn these into a concrete instruction for call_editor_agent, don't just resend the topic:\n${issues.join("\n")}`;
    }, {
        name: "review_newsletter",
        description: "Score the current newsletter draft against the quality rubric — structure, visual relevance, and groundedness, each 0-2, plus a pass/fail on whether it was actually saved in the real beehiiv format. Call this after reading the draft back (e.g. via the editor agent's report or a direct read), with your own honest scoring and evidence for each criterion. A disqualifying format failure or a total under 5/6 means it needs revision — use the returned issues to write a specific instruction for call_editor_agent rather than approving a draft that isn't ready.",
        schema: newsletterRubric,
    }
);

const beehiivTools = await getBeehiivMCP(KEEP_BEEHIIV_TOOLS);

export const managerTools = [callEditorAgent, callRelevanceFilterAgent, callUseCaseWriterAgent, callResearchAgent, reviewNewsletter, ...beehiivTools];