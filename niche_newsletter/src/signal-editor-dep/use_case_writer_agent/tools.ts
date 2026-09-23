// Capabilities: if use cases need to be tested (automation workflows) for any other cases,
// the agent should serve as a judge -> translate them into "here's how to put this into practice"
// Core cases: prompt engineering + AI output validation + automation workflows

import { z } from "zod";
import { YoutubeTranscript } from "youtube-transcript";
import { mkdir, writeFile } from "fs/promises";
import { tool, type ToolRuntime } from "@langchain/core/tools";
import { join } from 'path';
import { UseCaseWriterAgentState } from "./state.js";
import { applyFindAndReplace, appendFileEnsuringDir, readOrInitFile } from "../../shared/file_utils.js";
import { dataPaths } from "../../shared/paths.js";

const YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search";

type YoutubeSearchResponse = {
    items: Array<{
        id: { videoId: string };
        snippet: {
            title: string;
            description: string;
            channelTitle: string;
            publishedAt: string;
        };
    }>;
};

const readResearchFindings = tool(
    async (_input, runtime: ToolRuntime<typeof UseCaseWriterAgentState>) => {
        const researchTopic = runtime.state.researchTopic;
        const filePath = join(dataPaths.researchScratchPad(), `${researchTopic}_notes.md`);
        return await readOrInitFile(filePath);
    }, {
        name: "read_research_findings",
        description: "Read the research findings for this topic, as trimmed and summarized by the relevance filter agent. This is the material you're writing use cases from — always start here."
    }
);

const getVideoTranscript = tool(
    async ({videoIdOrUrl, videoTitle}) => {
        try {
            const transcript = await YoutubeTranscript.fetchTranscript(videoIdOrUrl);
            console.log(`Fetched ${transcript.length} segments.`);
        
            const videoId = videoTitle.toLowerCase().replace(" ", "_");
            const outDir = dataPaths.useCaseScratchPad();
            const outPath = join(outDir, `${videoId}_transcript.md`);
        
            const fullText = transcript.map((seg) => seg.text).join(" ");
            const markdown = `# Transcript: ${videoId}\n\nSource: ${videoIdOrUrl}\n\n${fullText}\n`;
            await writeFile(outPath, markdown, "utf-8");
        
            return `Saved transcript (${fullText.length} chars) to ${outPath}`
        } catch (error) {
            return `Failed to fetch transcript: ${error}`
        }
    }, {
        name: "get_video_transcript",
        description: "Get the transcript of the provided youtube video url",
        schema: z.object({
            videoIdOrUrl: z.string(),
            videoTitle: z.string().describe("Title to use, couple of words max, will be used for file name")
        })
    }
)

const searchVideos = tool(
    async ({ query, maxResults }) => {
        const apiKey = process.env.GOOGLE_PROJECT_KEY;
        if (!apiKey) {
            return "GOOGLE_PROJECT_KEY is not set — cannot search YouTube.";
        }

        const url = new URL(YOUTUBE_SEARCH_URL);
        url.searchParams.set("part", "snippet");
        url.searchParams.set("type", "video");
        url.searchParams.set("q", query);
        url.searchParams.set("maxResults", String(maxResults));
        url.searchParams.set("key", apiKey);

        const response = await fetch(url);
        if (!response.ok) {
            const body = await response.text();
            return `YouTube search failed (${response.status}): ${body}`;
        }

        const data = await response.json() as YoutubeSearchResponse;
        const results = data.items.map((item) => ({
            videoId: item.id.videoId,
            title: item.snippet.title,
            description: item.snippet.description,
            channel: item.snippet.channelTitle,
            publishedAt: item.snippet.publishedAt,
            url: `https://www.youtube.com/watch?v=${item.id.videoId}`,
        }));

        return JSON.stringify(results);
    }, {
        name: "search_videos",
        description: "Search YouTube for videos relevant to a query. Returns title, channel, publish date, and URL for each result — pass a result's videoIdOrUrl to get_video_transcript to pull its transcript.",
        schema: z.object({
            query: z.string().describe("the search query"),
            maxResults: z.number().optional().default(5).describe("max number of results to return (1-50)"),
        }),
    }
);

const YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos";

// Accepts either a bare video ID or a full/short YouTube URL.
function extractVideoId(input: string): string {
    const match = input.match(/(?:v=|youtu\.be\/|\/embed\/|\/shorts\/)([a-zA-Z0-9_-]{11})/);
    return match?.[1] ?? input;
}

type YoutubeVideosResponse = {
    items: Array<{
        id: string;
        snippet: {
            title: string;
            description: string;
            channelTitle: string;
            publishedAt: string;
        };
        statistics?: {
            viewCount?: string;
            likeCount?: string;
            commentCount?: string;
        };
        contentDetails?: {
            duration?: string;
        };
    }>;
};

const getVideoData = tool(
    async ({ videoIdsOrUrls }) => {
        const apiKey = process.env.GOOGLE_PROJECT_KEY;
        if (!apiKey) {
            return "GOOGLE_PROJECT_KEY is not set — cannot look up YouTube videos.";
        }

        const ids = videoIdsOrUrls.map(extractVideoId);

        const url = new URL(YOUTUBE_VIDEOS_URL);
        url.searchParams.set("part", "snippet,statistics,contentDetails");
        url.searchParams.set("id", ids.join(","));
        url.searchParams.set("key", apiKey);

        const response = await fetch(url);
        if (!response.ok) {
            const body = await response.text();
            return `YouTube video lookup failed (${response.status}): ${body}`;
        }

        const data = await response.json() as YoutubeVideosResponse;
        const results = data.items.map((item) => ({
            videoId: item.id,
            title: item.snippet.title,
            description: item.snippet.description,
            channel: item.snippet.channelTitle,
            publishedAt: item.snippet.publishedAt,
            duration: item.contentDetails?.duration,
            viewCount: item.statistics?.viewCount,
            likeCount: item.statistics?.likeCount,
            url: `https://www.youtube.com/watch?v=${item.id}`,
        }));

        return JSON.stringify(results);
    }, {
        name: "get_video_data",
        description: "Look up metadata (title, description, channel, publish date, duration, view/like counts) for known YouTube videos by ID or URL — up to 50 per call, 1 quota unit total regardless of how many. Use this instead of search_videos when you already have a video's ID or URL and just need fresh details on it.",
        schema: z.object({
            videoIdsOrUrls: z.array(z.string()).max(50).describe("Video IDs or YouTube URLs to look up"),
        }),
    }
);

const readHowTo = tool(
    async (_input, runtime: ToolRuntime<typeof UseCaseWriterAgentState>) => {
        const researchTopic = runtime.state.researchTopic;
        const fullPath = join(dataPaths.useCaseScratchPad(), `${researchTopic}_use_cases.md`);
        return await readOrInitFile(fullPath);
    }, {
        name: "read_how_to",
        description: "Read the current draft of your use-case write-up"
    }
);

const editHowTo = tool(
    async ({ to_replace, replace_with }, runtime: ToolRuntime<typeof UseCaseWriterAgentState>) => {
        const researchTopic = runtime.state.researchTopic;
        const fullPath = join(dataPaths.useCaseScratchPad(), `${researchTopic}_use_cases.md`);

        const outcome = await applyFindAndReplace(fullPath, to_replace, replace_with);
        if (outcome.status === "not_found") {
            return `"${to_replace}" not found in file (checked exact and whitespace-flexible matches).`;
        }
        if (outcome.status === "ambiguous") {
            return `"${to_replace}" found ${outcome.count} times — expected exactly one match, aborting edit.`;
        }

        return outcome.result;
    }, {
        name: "edit_how_to",
        description: "Edit the content of your use-case write-up",
        schema: z.object({
            to_replace: z.string().describe("Content to replace"),
            replace_with: z.string().describe("Content to replace with")
        })
    }
);

const addContent = tool(
    async ({ content }, runtime: ToolRuntime<typeof UseCaseWriterAgentState>) => {
        const researchTopic = runtime.state.researchTopic;
        const fullPath = join(dataPaths.useCaseScratchPad(), `${researchTopic}_use_cases.md`);
        await appendFileEnsuringDir(fullPath, content);

        return "Your use-case write-up has been updated";
    }, {
        name: "add_content_to_how_to",
        description: "Add content to your use-case write-up",
        schema: z.object({
            content: z.string().describe("Content to add"),
        })
    }
);

export const useCaseWriterTools = [readResearchFindings, readHowTo, editHowTo, addContent, getVideoTranscript, searchVideos, getVideoData];