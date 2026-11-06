// Draft the newsletter content + create the visuals when applicable
// Synthesise sources already gathered

import { base64, z } from "zod";
import { mkdir, writeFile } from "fs/promises";
import { randomUUID } from "node:crypto";
import { tool, type ToolRuntime } from "@langchain/core/tools";
import { HumanMessage, ToolMessage } from "@langchain/core/messages";
import { Command } from "@langchain/langgraph";
import { join } from 'path';
import { OpenRouter } from "@openrouter/sdk";
import type { ImageGenerationRequestAspectRatio } from "@openrouter/sdk/models";
import * as QuickChartModule from 'quickchart-js';
import type { ChartConfiguration } from 'quickchart-js';
import { DropboxResponseError } from 'dropbox';
import { getDropbox } from "../../shared/dropbox.js";
import { EditorAgentState } from "./state.js";
import { MODELS } from "../../models.js";
import { applyFindAndReplace, appendFileEnsuringDir, readOrInitFile } from "../../shared/file_utils.js";
import { getBeehiivMCP } from "../../shared/beehiiv_mcp.js"
import { getNotionMCP } from "../../shared/notion_mcp.js";
import { dataPaths } from "../../shared/paths.js";
import { Sandbox, CommandExitError, Template } from "e2b";
import { uploadToDropboxAndGetShareUrl } from "../../shared/upload_to_dropbox.js";

// Write tools are hidden for now, due to tier gate
const KEEP_BEEHIIV_TOOLS = new Set([
    // "edit_post",
    // "edit_post_content",
    "get_post",
    "get_post_content",
    "get_post_footer",
    "get_post_template_content",
    // "learn_post_authoring",
    // "learn_post_metadata",
    "list_post_templates",
    "list_posts",
    // "save_post",
    // "save_post_footer",
    // "save_post_theme",
    // "duplicate_post",
    // "save_split_test",
    
    "get_asset",
    "list_assets",
    // "save_file",
    // "save_image",
    // "update_asset",
    
    "list_content_tags",
    // "save_content_tag",

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
    // "notion-create-database",
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

// const SANDBOX_DEPS = "react@19.3.0 @resvg/resvg-js satori@0.63.2 @resvg/resvg-js tsx@4.23.13 @expo-google-fonts/inter@0.4.2 @expo-google-fonts/jetbrains-mono@0.4.1";
// const SANDBOX_TSCONFIG = JSON.stringify({
//     compilerOptions: { jsx: "react-jsx", module: "esnext", moduleResolution: "bundler", esModuleInterop: true },
// });
// const SANDBOX_PACKAGE_JSON = JSON.stringify({ name: "visual-gen", private: true, type: "module" });

// TS 7's nodenext resolution can't fully model this package's shape (conditional `exports`
// map + a `.d.ts` with no `"type"` field to disambiguate CJS/ESM) and falls back to an
// opaque type for both the namespace and its `.default` member — this cast restores the
// real, documented shape (constructor + setConfig/getUrl/...) rather than fighting the compiler.
interface QuickChartInstance {
    setConfig(chartConfig: string | ChartConfiguration): QuickChartInstance;
    setWidth(width: number): QuickChartInstance;
    setHeight(height: number): QuickChartInstance;
    setBackgroundColor(color: string): QuickChartInstance;
    setVersion(version: string): QuickChartInstance;
    getUrl(): string;
    getShortUrl(): Promise<string>;
    toBinary(): Promise<Buffer>;
    toDataUrl(): Promise<string>;
}
const QuickChart = QuickChartModule.default as unknown as new () => QuickChartInstance;


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
        myChart.setVersion("4");
        myChart.setConfig(config);
        if (width !== undefined) myChart.setWidth(width);
        if (height !== undefined) myChart.setHeight(height);
        if (backgroundColor !== undefined) myChart.setBackgroundColor(backgroundColor);

        let chartUrl;
        try {
            chartUrl = await myChart.getShortUrl();
        } catch {
            return "Failed: No chart was generated!";
        }


        return new Command({
            update: {
                messages: [
                    new ToolMessage({ content: `Chart has been created: ${chartUrl}`, tool_call_id: runtime.toolCallId }),
                    new HumanMessage({content: [
                            {type: "image", url: chartUrl}
                        ]
                    })
                ],
                chartUrl
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

const createRichVisuals = tool(
    async ({ fileName, code, editExistingVisual }, runtime: ToolRuntime<typeof EditorAgentState>) => {
        const e2bApiKey = process.env.E2B_API_KEY;
        if (!e2bApiKey) {
            return "E2B_API_KEY is not set — cannot run the visual-generation sandbox.";
        }
        const dropbox = getDropbox();
        if (typeof dropbox === "string") return dropbox;

        const existingSandboxId = runtime.state.sandboxId;
        let sandbox: Sandbox | undefined;
        let isReconnect = false;
        try {
            if (existingSandboxId && editExistingVisual) {
                sandbox = await Sandbox.connect(existingSandboxId);
                isReconnect = true;
            } else {
                // 5 minutes covers a cold `npm install` plus the render; extended below
                // once the render succeeds, to give a reviewer time to look at it.
                sandbox = await Sandbox.create("newsletter-visual-gen", { timeoutMs: 2 * 60_000 });
            }
        } catch (error) {
            return `Could not ${existingSandboxId ? "reconnect to" : "start"} the sandbox: ${error}`;
        }

        try {
            await sandbox.files.write([
                { path: "generate.tsx", data: code },
                // ...(isReconnect ? [] : [
                //     { path: "tsconfig.json", data: SANDBOX_TSCONFIG },
                //     { path: "package.json", data: SANDBOX_PACKAGE_JSON },
                // ])
            ]);

            // if (!isReconnect) {
            //     try {
            //         await sandbox.commands.run(`npm install --no-audit --no-fund ${SANDBOX_DEPS}`, { timeoutMs: 180_000 });
            //     } catch (error) {
            //         await sandbox.kill()
            //         if (error instanceof CommandExitError) {
            //             return `Sandbox dependency install failed:\n${error.stderr || error.stdout}`;
            //         }
            //         throw error;
            //     }
            // }

            try {
                await sandbox.commands.run("npx tsx generate.tsx", { timeoutMs: 90_000 });
            } catch (error) {
                const persistedSandboxId = sandbox.sandboxId;
                if (error instanceof CommandExitError) {
                    return new Command({
                        update: {
                            sandboxId: persistedSandboxId,
                            messages: [new ToolMessage({ content: `Your script failed to run inside the sandbox:\n${error.stderr || error.stdout}`, tool_call_id: runtime.toolCallId })],
                        },
                    });
                }
                throw error;
            }

            let pngBytes: Uint8Array;
            try {
                pngBytes = await sandbox.files.read("output.png", { format: "bytes" });
            } catch {
                return `Your script ran without error but never wrote "output.png" — call resvg with 'output.png' at the end of it to render it.`;
            }

            const name = fileName.toLowerCase().replace(/\s+/g, "_");
            const dropboxPath = `/newsletter_images/rich_visuals/${name}.png`;
            let documentUrl: string;
            try {
                documentUrl = await uploadToDropboxAndGetShareUrl(dropbox, dropboxPath, Buffer.from(pngBytes));
            } catch (error) {
                return error instanceof Error ? error.message : `Failed to host the generated document: ${error}`;
            }

            // Give a reviewer room to look at the result before the sandbox auto-kills;
            // finalize_document kills it for real once a human approves.
            await sandbox.setTimeout(30 * 60_000);

            return new Command({
                update: {
                    sandboxId: sandbox.sandboxId,
                    // pendingDocumentUrl: documentUrl,
                    messages: [
                        new ToolMessage({ content: [ 
                            {type: "text", text: `"${fileName}" rendered with the following url (${documentUrl}), you should review it (attached) and check if you are content with the result. If not, go back to correct it.`},
                            ], tool_call_id: runtime.toolCallId }),
                        new HumanMessage({content: [
                            {type: "image", source_type: "base64", data: Buffer.from(pngBytes).toString("base64"), mime_type: "png", metadata: { filename: `${name}.png` }}
                        ]})
                    ],
                },
            });
        } catch (error) {
            await sandbox.kill();
            return `Visual generation failed: ${error}`;
        }
    }, {
        name: "create_rich_visuals",
        description: [
            "Create a designed graphic with exact text — flowchart, process or architecture overview, comparison table, stat/key-number card, timeline, checklist, pull-quote, annotated schematic, infographic, or section banner. Use it for everything that is not a data chart (use create_chart) or a hero/illustration image (use generate_image).",
            "You supply a TypeScript script as `code`; it is saved as generate.tsx and run with tsx in a sandbox that has react, satori and @resvg/resvg-js preinstalled. The script must lay the graphic out with Satori (JSX + flexbox styles), render it to PNG with resvg, and write it to `output.png` in the working directory. The PNG is hosted and its URL returned, and the render is attached so you can review it before embedding.",
            "Fonts: Inter and JetBrains Mono are installed as static TTFs, e.g. node_modules/@expo-google-fonts/inter/800ExtraBold/Inter_800ExtraBold.ttf (pattern: node_modules/@expo-google-fonts/<package>/<weight>/<Family>_<weight>.ttf). Read them with fs and pass them to Satori's `fonts` option; WOFF2 is not supported.",
            "Satori rules: flexbox only (no CSS grid); every element with more than one child needs display: 'flex'; set boxSizing: 'border-box' on the root; draw arrows, icons and symbols as inline SVG, not text glyphs (the fonts lack them, and emoji are unsupported).",
            "Design for email: 1200 px wide canvas (shown at 600 px), text readable at half size, strong contrast, solid background, one idea per graphic, all text in Spanish.",
            "If the render has problems, fix the script and call again with editExistingVisual: true.",
        ].join("\n\n"),
        schema: z.object({
            fileName: z.string().describe("Short descriptive name for the visual, used as the hosted file name (e.g. 'flujo de aprobacion')"),
            code: z.string().describe("Complete TypeScript source for generate.tsx. Must write the rendered PNG to output.png."),
            editExistingVisual: z.boolean().describe("Set to true to re-run in the same sandbox after fixing your previous visual; false (default) starts a fresh sandbox").default(false)
        })
    }
);

const getResearchFindings = tool(
    async (_input, runtime: ToolRuntime<typeof EditorAgentState>) => {
        const researchTopic = runtime.state.researchTopic;
        const researchFilePath = join(dataPaths.researchScratchPad(), `${researchTopic}_notes.md`);
        const useCaseFilePath = join(dataPaths.useCaseScratchPad(), `${researchTopic}_use_cases.md`);
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
        const dropbox = getDropbox();
        if (typeof dropbox === "string") return dropbox;

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
            });
            shareUrl = shareResult.result.url;
        } catch (error) {
            // A shared link may already exist for this path (e.g. a retried call) — Dropbox
            // reports that as an error carrying the existing link, which is just as usable.
            // The SDK's `.error` is the whole response body, so the tagged-union error is at
            // `.error.error`. Dropbox only includes the existing link's metadata when no custom
            // settings were sent, which is why `settings` is left out above.
            const existingUrl = (error instanceof DropboxResponseError
                ? (error.error as { error?: { shared_link_already_exists?: { metadata?: { url?: string } } } })
                    ?.error?.shared_link_already_exists?.metadata?.url
                : undefined);
            if (!existingUrl) {
                return `Dropbox share-link creation failed: ${error}`;
            }
            shareUrl = existingUrl;
        }
        const imgUrl = JSON.stringify({ imageUrl: toDirectDropboxUrl(shareUrl), prompt });
        return new Command({
            update: {
                messages: [
                    new ToolMessage({ content: `Image has been saved successfully: ${imgUrl}`, tool_call_id: runtime.toolCallId }),
                    new HumanMessage({content: [
                            {type: "image", url: imgUrl}
                        ]
                    })
                ],
                imageUrl: imgUrl
            },
        });
    }, {
        name: "generate_image",
        description: "Generate an image from a text prompt via OpenRouter's image API and host it on Dropbox. Returns { imageUrl, prompt } where imageUrl is a public, directly-embeddable link ready to drop into notion or beehiiv.",
        schema: z.object({
            prompt: z.string().describe("Detailed description of the image to generate"),
            aspectRatio: z.string().optional().default("16:9").describe("Aspect ratio, e.g. '16:9', '1:1', '4:3'"),
        }),
    }
);

const notionTools = await getNotionMCP(KEEP_NOTION_TOOLS, { envVars: ["NOTION_DRAFT_PAGE"] });
const beehiivTools = await getBeehiivMCP(KEEP_BEEHIIV_TOOLS);

export const editorTools = [getResearchFindings, generateImages, createChart, createRichVisuals, ...beehiivTools, ...notionTools];