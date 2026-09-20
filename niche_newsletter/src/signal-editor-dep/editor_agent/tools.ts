// Draft the newsletter content + create the visuals when applicable
// Synthesise sources already gathered

import { z } from "zod";
import { mkdir, writeFile } from "fs/promises";
import { randomUUID } from "node:crypto";
import { tool, type ToolRuntime } from "@langchain/core/tools";
import { ToolMessage } from "@langchain/core/messages";
import { Command } from "@langchain/langgraph";
import { join } from 'path';
import { OpenRouter } from "@openrouter/sdk";
import type { ImageGenerationRequestAspectRatio } from "@openrouter/sdk/models";
import * as QuickChartModule from 'quickchart-js';
import type { ChartConfiguration } from 'quickchart-js';
import { Dropbox, DropboxResponseError } from 'dropbox';
import { EditorAgentState } from "./state.js";
import { MODELS } from "../../models.js";
import { applyFindAndReplace, appendFileEnsuringDir, readOrInitFile } from "../../shared/file_utils.js";
import { getBeehiivMCP } from "../../shared/beehiiv_mcp.js"
import { getNotionMCP } from "../../shared/notion_mcp.js";

const KEEP_BEEHIIV_TOOLS = new Set([
    "edit_post",
    "edit_post_content",
    "edit_post_template",
    "edit_post_template_content",
    "get_post",
    "get_post_content",
    "get_post_footer",
    "get_post_template_content",
    "learn_post_authoring",
    "learn_post_metadata",
    "list_post_templates",
    "list_posts",
    "save_post",
    "save_post_footer",
    "save_post_template",
    "save_post_template_theme",
    "save_post_theme",
    "duplicate_post",
    "duplicate_post_template",
    "save_split_test",
    // Visuals/assets
    // "generate_image",
    "get_asset",
    // "get_image_generation_status",
    "list_assets",
    "save_file",
    "save_image",
    "update_asset",
    // Metadata
    "list_content_tags",
    "save_content_tag",
    // Self-service API discovery
    "read_documentation",
    "search_documentation",
])

const KEEP_NOTION_TOOLS = new Set([
    "notion-search",
    "notion-fetch",
    "notion-create-pages",
    "notion-update-page",
    "notion-move-pages",
    "notion-duplicate-page",
    "notion-list-private-pages",
    "notion-list-recent-pages",
    "notion-list-favorite-pages",
    "notion-create-database",
    "notion-update-data-source",
    "notion-create-view",
    "notion-update-view",
    "notion-create-attachment",
    "notion-create-file-upload",
    "notion-download-attachment",
    "notion-create-folder",
    "notion-update-folder",
    "notion-search-skills",
    "notion-convert-page-to-skill",
    "notion-get-users",
    "notion-get-async-task",
]);

// TS 7's nodenext resolution can't fully model this package's shape (conditional `exports`
// map + a `.d.ts` with no `"type"` field to disambiguate CJS/ESM) and falls back to an
// opaque type for both the namespace and its `.default` member — this cast restores the
// real, documented shape (constructor + setConfig/getUrl/...) rather than fighting the compiler.
interface QuickChartInstance {
    setConfig(chartConfig: string | ChartConfiguration): QuickChartInstance;
    setWidth(width: number): QuickChartInstance;
    setHeight(height: number): QuickChartInstance;
    setBackgroundColor(color: string): QuickChartInstance;
    getUrl(): string;
    getShortUrl(): Promise<string>;
    toBinary(): Promise<Buffer>;
    toDataUrl(): Promise<string>;
}
const QuickChart = QuickChartModule.default as unknown as new () => QuickChartInstance;

const SCRATCH_PAD_DIR = "src/signal-editor-dep/use_case_writer_agent/scratch_pad/";
const RESEARCH_SCRATCH_PAD_DIR = "src/signal-editor-dep/research_agent/scratch_pad/";

// Chart.js's real config space is huge and chart-type-specific (radar uses `scales.r`,
// doughnut uses `cutout`, etc.) — modeling all of it in zod isn't practical, and quickchart-js
// itself types the config as `Record<string, any>` for the same reason. This schema spells out
// the fields common to every chart type (for the model's guidance) and leaves `.loose()`
// at each level so any other valid Chart.js key for the chosen type still gets through untouched.
const chartConfigSchema = z.object({
    type: z.enum([
        "bar", "line", "pie", "doughnut", "radar", "polarArea", "bubble", "scatter", "radialGauge", "speedometer",
    ]).describe("Chart.js chart type (radialGauge/speedometer are QuickChart extras)"),
    data: z.object({
        labels: z.array(z.union([z.string(), z.number()])).optional()
            .describe("Category / x-axis labels, one per data point"),
        datasets: z.array(
            z.object({
                label: z.string().optional(),
                data: z.array(z.any())
                    .describe("Series values — plain numbers for most chart types, {x,y} objects for scatter/bubble"),
                backgroundColor: z.union([z.string(), z.array(z.string())]).optional(),
                borderColor: z.union([z.string(), z.array(z.string())]).optional(),
                borderWidth: z.number().optional(),
                fill: z.boolean().optional(),
                tension: z.number().optional().describe("Line curve smoothing, 0-1"),
            }).loose()
        ).min(1).describe("One or more data series"),
    }).loose(),
    options: z.object({
        plugins: z.record(z.string(), z.any()).optional()
            .describe("e.g. { title: { display: true, text: '...' }, legend: {...}, datalabels: {...} }"),
        scales: z.record(z.string(), z.any()).optional()
            .describe("Axis config, e.g. { y: { beginAtZero: true } } (radar/polarArea use scales.r instead)"),
        responsive: z.boolean().optional(),
    }).loose().optional()
        .describe("Any valid Chart.js options object — not limited to the fields listed here"),
}).loose()
    .describe("A Chart.js configuration object. Common fields are structured here for guidance, but any additional valid Chart.js key for the chosen chart type (e.g. `cutout` for doughnut, `scales.r` for radar) is accepted as-is.");

const createChart = tool(
    async ({ config, width, height, backgroundColor }, runtime: ToolRuntime<typeof EditorAgentState>) => {
        const myChart = new QuickChart();
        myChart.setConfig(config);
        if (width !== undefined) myChart.setWidth(width);
        if (height !== undefined) myChart.setHeight(height);
        if (backgroundColor !== undefined) myChart.setBackgroundColor(backgroundColor);
        
        return new Command({
            update: {
                messages: [new ToolMessage({ content: "Chart has been created.", tool_call_id: runtime.toolCallId })],
                chartUrl: myChart.getUrl()
            },
        });
    }, {
        name: "create_chart",
        description: "Render a Chart.js chart (bar, line, pie, doughnut, radar, scatter, bubble, ...) via QuickChart and return a hosted, directly-embeddable image URL for a beehiiv image block or <img> tag.",
        schema: z.object({
            config: chartConfigSchema,
            width: z.number().optional().describe("Image width in px (default 500)"),
            height: z.number().optional().describe("Image height in px (default 300)"),
            backgroundColor: z.string().optional().describe("Canvas background color, e.g. '#ffffff' or 'transparent' (default transparent)"),
        }),
    }
)

const getResearchFindings = tool(
    async (_input, runtime: ToolRuntime<typeof EditorAgentState>) => {
        const researchTopic = runtime.state.researchTopic;
        const researchFilePath = join(RESEARCH_SCRATCH_PAD_DIR, `${researchTopic}_notes.md`);
        const useCaseFilePath = join(SCRATCH_PAD_DIR, `${researchTopic}_use_cases.md`);
        const researchContent = await readOrInitFile(researchFilePath);
        const useCaseContent = await readOrInitFile(useCaseFilePath);
        const combined = `Research findings: ${researchContent}\n\n Use case description (if provided): ${useCaseContent}`
        return combined;
    }, {
        name: "get_research_findings",
        description: "Read the research findings and use case descriptions for this topic. This is the material you're writing the post from — always start here."
    }
);

// Dropbox share links land on a preview page by default (`?dl=0`); swapping in `raw=1`
// makes the same URL serve the image bytes directly, which is what an <img src> or a
// beehiiv image block needs.
function toDirectDropboxUrl(shareUrl: string): string {
    const url = new URL(shareUrl);
    url.searchParams.delete("dl");
    url.searchParams.set("raw", "1");
    return url.toString();
}

const generateImages = tool(
    async ({ prompt, aspectRatio }, runtime: ToolRuntime<typeof EditorAgentState>) => {
        const openRouterKey = process.env.OPENROUTER_API_KEY;
        if (!openRouterKey) {
            return "OPENROUTER_API_KEY is not set — cannot generate an image.";
        }
        const dropboxToken = process.env.DROPBOX;
        if (!dropboxToken) {
            return "DROPBOX access token is not set — cannot host the generated image.";
        }

        const openRouter = new OpenRouter({ apiKey: openRouterKey });

        let genResult;
        try {
            genResult = await openRouter.images.generate({
                imageGenerationRequest: {
                    model: MODELS.IMAGE_GENERATION_MODEL,
                    prompt,
                    n: 1,
                    aspectRatio: aspectRatio as ImageGenerationRequestAspectRatio,
                    outputFormat: "png",
                },
            });
        } catch (error) {
            return `Image generation failed: ${error}`;
        }

        // The SDK's return type covers both streaming and non-streaming responses; we
        // never request streaming, so a ReadableStream here would mean the API behaved
        // unexpectedly rather than a case this tool needs to handle.
        if (genResult instanceof ReadableStream) {
            return "Image generation unexpectedly returned a stream — this tool only supports non-streaming responses.";
        }

        const image = genResult.data?.[0];
        if (!image?.b64Json) {
            return "Image generation returned no image data.";
        }
        const imageBytes = Buffer.from(image.b64Json, "base64");
        const extension = image.mediaType?.split("/")[1] ?? "png";

        const researchTopic = runtime.state.researchTopic;
        const dropboxPath = `/newsletter_images/${researchTopic}/${Date.now()}_${randomUUID().slice(0, 8)}.${extension}`;

        const dropbox = new Dropbox({ accessToken: dropboxToken });

        let uploadedPath: string;
        try {
            const uploadResult = await dropbox.filesUpload({
                path: dropboxPath,
                contents: imageBytes,
                mode: { '.tag': 'add' },
                autorename: true,
                mute: true,
            });
            uploadedPath = uploadResult.result.path_lower ?? dropboxPath;
        } catch (error) {
            return `Dropbox upload failed: ${error}`;
        }

        let shareUrl: string;
        try {
            const shareResult = await dropbox.sharingCreateSharedLinkWithSettings({
                path: uploadedPath,
                settings: { audience: { '.tag': 'public' } },
            });
            shareUrl = shareResult.result.url;
        } catch (error) {
            // A shared link may already exist for this path (e.g. a retried call) — Dropbox
            // reports that as an error carrying the existing link, which is just as usable.
            // The SDK already unwraps the response to the tagged-union error (`.error`), and
            // types `shared_link_already_exists` as a generic `Object`; `metadata.url` below
            // is the shape Dropbox's API actually returns for this case.
            const existingUrl = (error instanceof DropboxResponseError
                ? (error.error as { shared_link_already_exists?: { metadata?: { url?: string } } })?.shared_link_already_exists?.metadata?.url
                : undefined);
            if (!existingUrl) {
                return `Dropbox share-link creation failed: ${error}`;
            }
            shareUrl = existingUrl;
        }
        const imgUrl = JSON.stringify({ imageUrl: toDirectDropboxUrl(shareUrl), prompt });
        return new Command({
            update: {
                messages: [new ToolMessage({ content: "Image has been saved successfully.", tool_call_id: runtime.toolCallId })],
                imageUrl: imgUrl
            },
        });
    }, {
        name: "generate_image",
        description: "Generate an image from a text prompt via OpenRouter's image API and host it on Dropbox. Returns { imageUrl, prompt } where imageUrl is a public, directly-embeddable link ready to drop into a beehiiv image block or an <img> tag.",
        schema: z.object({
            prompt: z.string().describe("Detailed description of the image to generate"),
            aspectRatio: z.string().optional().default("16:9").describe("Aspect ratio, e.g. '16:9', '1:1', '4:3'"),
        }),
    }
);

const notionTools = await getNotionMCP(KEEP_NOTION_TOOLS);
const beehiivTools = await getBeehiivMCP(KEEP_BEEHIIV_TOOLS);

export const editorTools = [getResearchFindings, generateImages, createChart, ...notionTools, ...beehiivTools];