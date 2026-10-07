// Capabilities: review social media content + read and approve potential leads
import { z } from "zod";
import { tool, type ToolRuntime } from "@langchain/core/tools";
import { HumanMessage, ToolMessage } from "@langchain/core/messages";
import { Command, INTERRUPT, isInterrupted } from "@langchain/langgraph";
import { type AgentStateType, smPostRubric } from "./state.js";
import type { SMPostRubricType } from "./state.js";
import { getNotionMCP } from "../../shared/notion_mcp.js";
import { streamAgents } from "../../shared/progress_update.js";
import { ActorClient, ApifyClient, type ActorRun } from "apify-client";
import { transcribeVideoUrls } from "../../shared/transcribe.js";

const KEEP_NOTION_TOOLS = new Set([
    "notion-search",
    "notion-fetch",
    "notion-search-skills",
    // "notion-get-users",
]);

const TIKTOK_ACTOR = "clockworks/tiktok-scraper";
const INSTAGRAM_ACTOR = "apify/instagram-hashtag-scraper";

function getApifyClient(): ApifyClient | null {
    const token = process.env.APIFY_API_KEY;
    if (!token) {
        console.warn("No api key has been set for Apify tool");
        return null;
    }
    return new ApifyClient({ token });
}

interface TiktokVideoDetails {
    id: string,
    caption?: string | undefined,
    createTime?: number | undefined,
    webVideoUrl: string,
    diggCount: number,
    shareCount: number,
    playCount: number,
    repostCount: number,
    // foundVia?: string,
    [key: string]: unknown;
}

interface InstagramVideoDetails {
    id: string,
    type: string,
    caption?: string | undefined,
    videoUrl: string,
    url: string,
    likesCount: number,
    videoViewCount: number,
    videoPlayCount: number,
    reshareCount: number,
    commentsCount?: number | undefined,
    ownerUsername?: string | undefined,
    timestamp?: string | undefined,
    videoDuration?: number | undefined,
    [key: string]: unknown;
}

type handoffContract = {
    task_id: string;
    objectives: string[];
    constraints: string[];
    deliverables: string[];
};

const handoffSchema = z.object({
    task_id: z.string().describe("Short unique id for this assignment"),
    objectives: z.array(z.string()).describe("What this call should accomplish"),
    constraints: z.array(z.string()).describe("Narrowing: niche/keyword direction, minimum followers, how many accounts, what to leave out"),
    deliverables: z.array(z.string()).describe("What you expect back"),
});

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

const callOutreachAgent = tool(
    async (instruction: handoffContract, runtime: ToolRuntime<AgentStateType>) => {
        const { OutreachAgent } = await import("../user_outreach_agent/agent.js");
        const managerThreadId = runtime.config.configurable?.thread_id as string | undefined
        const threadId = `${managerThreadId ?? "unknown"}:outreach_agent`;
        const result = await streamAgents(
            OutreachAgent,
            "user_outreach_agent",
            { messages: [new HumanMessage({content: JSON.stringify(instruction)})] },
            threadId,
            runtime
        );

        return new Command({
            update: {
                messages: [new ToolMessage({ content: lastMessageContent(result), tool_call_id: runtime.toolCallId })],
            },
        });
    }, {
        name: "call_user_outreach_agent",
        description: "Call this agent to find Instagram accounts with a large following in the newsletter's niche (pages that already collect the target audience) and log them as leads in Notion. It only sources and logs — it never contacts anyone. Its reply is a short summary; the full list lives in Notion, which you can read with notion-search / notion-fetch.",
        schema: handoffSchema,
    }
);

const findTrendingReels = tool(
    async ({ keywords, hashtags }) => {
        const client = getApifyClient();
        if (!client) {
            return "APIFY_API_KEY is not set — cannot search Tiktok.";
        }

        if (keywords.length === 0 && hashtags.length === 0) {
            return "Provide at least one keyword or hashtag to search Tiktok.";
        }

        let videos: TiktokVideoDetails[];
        try {
            const run = await client.actor(TIKTOK_ACTOR).call({
                hashtags: hashtags,
                profileScrapeSections: "videos",
                maxProfilesPerQuery: 60,
                searchSection: "video",
                searchQueries: keywords
            });
            const { items } = await client.dataset<TiktokVideoDetails>(run.defaultDatasetId).listItems();
            videos = items.map((video) => ({
                id: video.id,
                caption: video.caption,
                createTime: video.createTime,
                webVideoUrl: video.webVideoUrl,
                diggCount: video.diggCount,
                shareCount: video.shareCount,
                playCount: video.playCount,
                repostCount: video.repostCount,

            }))
        } catch (error) {
            return `Failed to search Tiktok videos: ${error}`;
        }

        return JSON.stringify(videos);
    }, {
        name: "find_trending_reels",
        description: "Search Tiktok for videos matching the given keywords and/or hashtags. Returns, per qualifying videos, its id, caption, create time, url, like count, share count, view count, repost count.",
        schema: z.object({
            keywords: z.array(z.string()).optional().default([])
                .describe("Search terms to discover Tiktok videos by"),
            hashtags: z.array(z.string()).optional().default([])
                .describe("Hashtags to discover Tiktok videos by"),
        }),
    }
);

const findInstagramReels = tool(
    async ({ keywords, hashtags}) => {
        const client = getApifyClient();
        if (!client) {
            return "APIFY_API_KEY is not set — cannot search Instagram.";
        }

        if (keywords.length === 0 && hashtags.length === 0) {
            return "Provide at least one keyword or hashtag to search Instagram.";
        }

        if (keywords.length > 0 && hashtags.length > 0) {
            return "Provide either keywords or hashtags to search Instagram, not both.";
        }

        let reels: InstagramVideoDetails[];
        let run: ActorRun | undefined;
        try {
            if (keywords.length > 0) {
                run = await client.actor(INSTAGRAM_ACTOR).call({
                    hashtags: keywords,
                    keywordSearch: true,
                    resultsType: "reels",
                    resultsLimit: 60,
                });
            }
            else if (hashtags.length > 0) {
                run = await client.actor(INSTAGRAM_ACTOR).call({
                    hashtags: hashtags,
                    resultsType: "reels",
                    resultsLimit: 60,
                });
            }

            if (!run) {
                return "Provide at least one keyword or hashtag to search Instagram.";
            }

            const { items } = await client.dataset<InstagramVideoDetails>(run.defaultDatasetId).listItems();
            reels = items
                .filter((reel) => reel.url && reel.videoUrl)
                .map((reel) => ({
                    id: reel.id,
                    type: reel.type,
                    ownerUsername: reel.ownerUsername,
                    caption: reel.caption,
                    timestamp: reel.timestamp,
                    url: reel.url,
                    videoUrl: reel.videoUrl,
                    videoDuration: reel.videoDuration,
                    likesCount: reel.likesCount,
                    commentsCount: reel.commentsCount,
                    videoViewCount: reel.videoViewCount,
                    videoPlayCount: reel.videoPlayCount,
                    reshareCount: reel.reshareCount,
                }))
                .sort((a, b) => (b.videoPlayCount ?? b.videoViewCount ?? 0) - (a.videoPlayCount ?? a.videoViewCount ?? 0));
        } catch (error) {
            return `Failed to search Instagram reels: ${error}`;
        }

        return JSON.stringify(reels);
    }, {
        name: "find_instagram_reels",
        description: "Search Instagram for reels matching the given keywords and/or hashtags. Returns, per reel, its id, owner, caption, post time, url, video url, duration, like count, comment count, view/play count and reshare count, most-played first. Pass the `url` (not `videoUrl`) to transcribe_video_content.",
        schema: z.object({
            keywords: z.array(z.string()).optional().default([])
                .describe("Search terms to discover Instagram reels by"),
            hashtags: z.array(z.string()).optional().default([])
                .describe("Hashtags to discover Instagram reels by"),
            maxResults: z.number().int().min(1).max(200).optional().default(30)
                .describe("Maximum number of reels to fetch"),
        }),
    }
);

const transcribeVideoContent = tool(
    async ({ urls }) => {
        const results = await transcribeVideoUrls(urls);
        return JSON.stringify(results.map((r) =>
            r.ok
                ? { url: r.url, videoId: r.transcript.videoId, cached: r.cached, text: r.transcript.text }
                : { url: r.url, error: r.error }
        ));
    }, {
        name: "transcribe_video_content",
        description: "Transcribe the speech in Tiktok videos and Instagram reels. Takes an array of video URLs — Tiktok webVideoUrl values from find_trending_reels and/or Instagram reel url values from find_instagram_reels (the post permalink, not the videoUrl CDN link) — and returns, per URL, the transcript text or an error. Results are cached per video, so repeat URLs are free. Failures on one URL do not affect the others.",
        schema: z.object({
            urls: z.array(z.url()).min(1).describe("Tiktok video or Instagram reel URLs to transcribe"),
        }),
    }
)

const notionTools = await getNotionMCP(KEEP_NOTION_TOOLS);

export const managerTools = [reviewSocialPost, sendReviewAnswerToSMAgent, callSMAgent, callOutreachAgent, findTrendingReels, findInstagramReels, transcribeVideoContent, ...notionTools];