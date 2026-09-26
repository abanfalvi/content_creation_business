// Capabilities: review social media content + read and approve potential leads
import { z } from "zod";
import { tool, type ToolRuntime } from "@langchain/core/tools";
import { HumanMessage, ToolMessage } from "@langchain/core/messages";
import { Command, INTERRUPT, isInterrupted } from "@langchain/langgraph";
import { type AgentStateType, smPostRubric } from "./state.js";
import type { SMPostRubricType } from "./state.js";
import { getNotionMCP } from "../../shared/notion_mcp.js";
import { streamAgents } from "../../shared/progress_update.js";

const KEEP_NOTION_TOOLS = new Set([
    "notion-search",
    "notion-fetch",
    "notion-search-skills",
    // "notion-get-users",
]);

type handoffContract = {
    task_id: string;
    objectives: string[];
    constraints: string[];
    deliverables: string[];
};

function lastMessageContent(result: { messages: { content: unknown }[] }): string {
    const last = result.messages.at(-1);
    return typeof last?.content === "string" ? last.content : JSON.stringify(last?.content ?? "");
}


function extractImageUrls(pending: unknown): string[] {
    if (!pending || typeof pending !== "object") return [];
    const args = (pending as { args?: unknown }).args;
    if (!args || typeof args !== "object") return [];
    const assets = (args as { assets?: unknown }).assets;
    if (!Array.isArray(assets)) return [];

    return assets
        .map((asset) => {
            const typed = asset as { image?: { url?: string }; document?: { thumbnailUrl?: string } } | undefined;
            return typed?.image?.url ?? typed?.document?.thumbnailUrl;
        })
        .filter((url): url is string => typeof url === "string");
}

function buildPendingReviewMessages(pending: unknown, toolCallId: string): (ToolMessage | HumanMessage)[] {
    const messages: (ToolMessage | HumanMessage)[] = [
        new ToolMessage({
            content: `Social media agent is paused, awaiting your review before it publishes/schedules:\n${JSON.stringify(pending)}\n\nUse review_social_post to score it, then send_review_answer_to_sm_agent to resume.`,
            tool_call_id: toolCallId,
        }),
    ];

    const imageUrls = extractImageUrls(pending);
    if (imageUrls.length > 0) {
        messages.push(new HumanMessage({
            content: [
                { type: "text", text: "The design for the pending post, for you to actually look at — judge review_social_post's formatCorrect against this, not just the metadata above." },
                ...imageUrls.map(url => ({ type: "image" as const, url })),
                {type: "text", text: "Below is the post template to compare the proposed post against"},
                {type: "image", url: "<placeholder>"}
            ],
        }));
    }

    return messages;
}

const reviewSocialPost = tool(
    async (rubric: SMPostRubricType) => {
        if (rubric.formatCorrect) {
            return `The post is approved. Use send_review_answer_to_sm_agent with approved: true to let it publish/schedule.`;
        }

        return `Needs revision! Turn this into a concrete instruction for send_review_answer_to_sm_agent's feedback (approved: false), don't just resend the topic:\n${rubric.formatCorrectEvidence}`;
    }, {
        name: "review_social_post",
        description: "Score the pending social post (from the interrupt payload call_social_media_agent returned) against the quality rubric — whether it stays consistent with the 'The AI Skill Brief' template, with your evidence either way. Call this before send_review_answer_to_sm_agent so your approval/rejection is backed by an actual judgment, not a rubber stamp.",
        schema: smPostRubric,
    }
);

const sendReviewAnswerToSMAgent = tool(
    async (reviewDecision: { approved: boolean; feedback?: string }, runtime: ToolRuntime<AgentStateType>) => {
        const { SMAgent } = await import("../sm_agent/agent.js");
        const managerThreadId = runtime.config.configurable?.thread_id as string | undefined
        const threadId = `${managerThreadId ?? "unknown"}:sm_agent`;

        const result = await SMAgent.invoke(
            new Command({ resume: reviewDecision }),
            { configurable: { thread_id: threadId } }
        );

        if (isInterrupted(result)) {
            const pending = result[INTERRUPT][0]?.value;
            return new Command({
                update: {
                    messages: buildPendingReviewMessages(pending, runtime.toolCallId),
                },
            });
        }

        return new Command({
            update: {
                messages: [new ToolMessage({ content: lastMessageContent(result), tool_call_id: runtime.toolCallId })],
            },
        });
    }, {
        name: "send_review_answer_to_sm_agent",
        description: "Resume the social media agent's paused post (paused by call_social_media_agent, scored with review_social_post) with your review decision. Approving lets it actually publish/schedule the post as-is; rejecting sends it back with concrete feedback to revise before trying again.",
        schema: z.object({
            approved: z.boolean().describe("Whether to approve the pending post for publishing/scheduling as-is"),
            feedback: z.string().optional().describe("Required when approved is false — concrete, specific feedback for the social media agent to revise the post"),
        }),
    }
)

const callSMAgent = tool(
    async (instruction: handoffContract, runtime: ToolRuntime<AgentStateType>) => {
        const { SMAgent } = await import("../sm_agent/agent.js");
        const managerThreadId = runtime.config.configurable?.thread_id as string | undefined
        const threadId = `${managerThreadId ?? "unknown"}:sm_agent`;
        const result = await streamAgents(
            SMAgent, 
            "social_media_agent",
            { messages: [new HumanMessage({content: JSON.stringify(instruction)})] },
            threadId,
            runtime
        );

        if (isInterrupted(result)) {
            const pending = result[INTERRUPT][0]?.value;
            return new Command({
                update: {
                    messages: buildPendingReviewMessages(pending, runtime.toolCallId),
                },
            });
        }

        return new Command({
            update: {
                messages: [new ToolMessage({ content: lastMessageContent(result), tool_call_id: runtime.toolCallId })],
            },
        });
    }, {
        name: "call_social_media_agent",
        description: "Call this agent to create the social media posts. It pauses before actually publishing/scheduling and waits for review — check the returned message for a pending review, then use review_social_post and send_review_answer_to_sm_agent to score it and let it proceed.",
    }
);

export const managerTools = [reviewSocialPost, sendReviewAnswerToSMAgent, callSMAgent];