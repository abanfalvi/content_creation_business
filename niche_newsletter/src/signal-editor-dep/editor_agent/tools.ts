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
import { EditorAgentState, type AgentStateType } from "./state.js";
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

function checkE2BApiKey(): boolean {
    const e2bApiKey = process.env.E2B_API_KEY;
    if (!e2bApiKey) {
        return false;
    } else {
        return true
    }
}

async function connectOrCreateSandbox(state: AgentStateType) {
    const existingSandboxId = state.sandboxId;
    if (existingSandboxId) {
        try {
            const sandbox = await Sandbox.connect(existingSandboxId);
            return sandbox;
        } catch {
            // Expired or unreachable: fall through and start a fresh one.
        }
    }

    let sandbox: Sandbox;
    try {
        // 5 minutes covers a cold `npm install`; every tool call extends it afterwards.
        sandbox = await Sandbox.create({ timeoutMs: 5 * 60_000 });
        return sandbox
    } catch (error) {
        return `Could not start the sandbox: ${error}`;
    }

    // const existingSandboxId = state.sandboxId;
    // let sandbox: Sandbox | undefined;
    // try {
    //     if (existingSandboxId) {
    //         sandbox = await Sandbox.connect(existingSandboxId);
    //     } else {
    //         // 5 minutes covers a cold `npm install` plus the render; extended below
    //         // once the render succeeds, to give a reviewer time to look at it.
    //         sandbox = await Sandbox.create("newsletter-visual-gen", { timeoutMs: 5 * 60_000 });
    //     }
    //     return sandbox
    // } catch (error) {
    //     return `Could not ${existingSandboxId ? "reconnect to" : "start"} the sandbox: ${error}`;
    // }
}

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

function sandboxReply(sandbox: Sandbox, runtime: ToolRuntime<typeof EditorAgentState>, content: string) {
    return new Command({
        update: {
            sandboxId: sandbox.sandboxId,
            messages: [new ToolMessage({ content, tool_call_id: runtime.toolCallId })],
        },
    });
}

// Keeps the sandbox alive between the agent's steps; each call pushes the deadline out.
const SANDBOX_IDLE_TIMEOUT_MS = 10 * 60_000;

const sandboxRead = tool(
    async ({ path }, runtime: ToolRuntime<typeof EditorAgentState>) => {
        if (!checkE2BApiKey()) {
            return "E2B_API_KEY is not set — cannot run the visual-generation sandbox.";
        }

        const sandbox = await connectOrCreateSandbox(runtime.state)
        if (typeof sandbox === "string") return sandbox
        await sandbox.setTimeout(SANDBOX_IDLE_TIMEOUT_MS);

        try {
            const fileContent = await sandbox.files.read(path);
            return sandboxReply(sandbox, runtime, fileContent);
        } catch {
            const entries = await sandbox.files.list("/home/user");
            return sandboxReply(sandbox, runtime, `File not found: ${path}. Files in /home/user: ${entries.map(e => e.name).join(", ")}`);
        }
    }, {
        name: "read_sandboxed_code",
        description: "Read a text file from the visual-generation sandbox (e.g. the generate.tsx you wrote earlier, to review or patch it). Relative paths resolve against /home/user, the sandbox's working directory. If the file does not exist, the reply lists the files in /home/user so you can correct the path. Only for text files; to look at the rendered PNG, use sandboxed_save_image.",
        schema: z.object({
            path: z.string().describe("Path of the file to read, relative to /home/user (e.g. 'generate.tsx') or absolute"),
        }),
    }
);

const sandboxCmdExec = tool(
    async ({ cmd }, runtime: ToolRuntime<typeof EditorAgentState>) => {
        if (!checkE2BApiKey()) {
            return "E2B_API_KEY is not set — cannot run the visual-generation sandbox.";
        }

        const sandbox = await connectOrCreateSandbox(runtime.state)
        if (typeof sandbox === "string") return sandbox
        await sandbox.setTimeout(SANDBOX_IDLE_TIMEOUT_MS);

        try {
            const result = await sandbox.commands.run(cmd, { timeoutMs: 90_000 });
            return sandboxReply(sandbox, runtime, `Exit code 0.\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`);
        } catch (error) {
            if (error instanceof CommandExitError) {
                return sandboxReply(sandbox, runtime, `Command failed (exit code ${error.exitCode}).\nstdout:\n${error.stdout}\nstderr:\n${error.stderr}`);
            }
            // Timeouts and transport errors: report them rather than crash the agent run.
            return sandboxReply(sandbox, runtime, `Command did not complete: ${error}`);
        }
    }, {
        name: "exec_cmd_sandboxed",
        description: "Run a shell command in the visual-generation sandbox and get back its exit code, stdout and stderr. The sandbox persists between your calls (files and installed packages stay), and the working directory is /home/user. Typical uses: run your script with `npx tsx generate.tsx`; inspect the environment with `ls`, `pwd` or `ls node_modules/@expo-google-fonts`; check that output.png exists. react, satori, @resvg/resvg-js, tsx and the Inter / JetBrains Mono fonts are preinstalled, so don't run npm install. A command is stopped after 90 seconds. A non-zero exit code is returned as text, not an error: read stderr, fix the script with write_sandboxed_code, and run again.",
        schema: z.object({
            cmd: z.string().describe("Shell command to run from /home/user, e.g. 'npx tsx generate.tsx'"),
        }),
    }
);

const sandboxSaveImage = tool(
    async ({ fileName }, runtime: ToolRuntime<typeof EditorAgentState>) => {
        if (!checkE2BApiKey()) {
            return "E2B_API_KEY is not set — cannot run the visual-generation sandbox.";
        }

        const dropbox = getDropbox();
        if (typeof dropbox === "string") return dropbox;

        const sandbox = await connectOrCreateSandbox(runtime.state)
        if (typeof sandbox === "string") return sandbox

        try {
            let pngBytes: Uint8Array;
            try {
                pngBytes = await sandbox.files.read("output.png", { format: "bytes" });
            } catch {
                const entries = await sandbox.files.list("/home/user");
                return sandboxReply(sandbox, runtime, `There is no "output.png" in /home/user — your script must render to that exact path with resvg. Files in /home/user: ${entries.map(e => e.name).join(", ")}`);
            }

            const name = fileName.toLowerCase().replace(/\s+/g, "_");
            const dropboxPath = `/newsletter_images/rich_visuals/${name}.png`;
            let documentUrl: string;
            try {
                documentUrl = await uploadToDropboxAndGetShareUrl(dropbox, dropboxPath, Buffer.from(pngBytes));
            } catch (error) {
                return sandboxReply(sandbox, runtime, error instanceof Error ? error.message : `Failed to host the generated document: ${error}`);
            }

            // Give a reviewer room to look at the result before the sandbox auto-kills;
            // finalize_document kills it for real once a human approves.
            await sandbox.setTimeout(20 * 60_000);

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
            return sandboxReply(sandbox, runtime, `Saving the image failed: ${error}`);
        }
    }, {
        name: "sandboxed_save_image",
        description: [
            "Publish the graphic your script rendered: reads /home/user/output.png from the sandbox, hosts it on Dropbox, and returns its URL together with the render attached as an image so you can review it. This is the last step of the visual workflow, and the only one with an effect outside the sandbox.",
            "Call it after exec_cmd_sandboxed has run your script successfully. If output.png is missing, the reply lists the files in /home/user so you can see where the script wrote it.",
            "Always look at the attached render before embedding the URL. If anything is clipped, misaligned or misspelled, fix generate.tsx with write_sandboxed_code, run it again with exec_cmd_sandboxed, and call this tool again with the same fileName.",
        ].join("\n\n"),
        schema: z.object({
            fileName: z.string().describe("Short descriptive name for the visual, used as the hosted file name (e.g. 'flujo de aprobacion')"),
        }),
    }
);

const sandboxWriteFiles = tool(
    async ({ path, content }, runtime: ToolRuntime<typeof EditorAgentState>) => {
        if (!checkE2BApiKey()) {
            return "E2B_API_KEY is not set — cannot run the visual-generation sandbox.";
        }

        const sandbox = await connectOrCreateSandbox(runtime.state)
        if (typeof sandbox === "string") return sandbox
        await sandbox.setTimeout(SANDBOX_IDLE_TIMEOUT_MS);

        try {
            await sandbox.files.write([{ path, data: content }]);
            return sandboxReply(sandbox, runtime, `Saved ${path} in the sandbox. Run it with exec_cmd_sandboxed.`);
        } catch (error) {
            return sandboxReply(sandbox, runtime, `Could not write ${path}: ${error}`);
        }
    }, {
        name: "write_sandboxed_code",
        description: [
            "Write a file into the visual-generation sandbox (creating or overwriting it). Use it to save the TypeScript script `generate.tsx` that draws a graphic with exact text — flowchart, process or architecture overview, comparison table, stat/key-number card, timeline, checklist, pull-quote, annotated schematic, infographic, or section banner. Use this workflow for everything that is not a data chart (use create_chart) or a hero/illustration image (use generate_image).",
            "Workflow: write_sandboxed_code (path 'generate.tsx') -> exec_cmd_sandboxed ('npx tsx generate.tsx') -> sandboxed_save_image. To fix a problem, write the corrected full file again and rerun; use read_sandboxed_code to look at what is currently there.",
            "The script runs with tsx from /home/user, where react, satori and @resvg/resvg-js are preinstalled. It must lay the graphic out with Satori (JSX + flexbox styles), render it to PNG with resvg, and write it to `output.png` in the working directory. Any other filename won't be picked up by sandboxed_save_image.",
            "Fonts: Inter and JetBrains Mono are installed as static TTFs, e.g. node_modules/@expo-google-fonts/inter/800ExtraBold/Inter_800ExtraBold.ttf (pattern: node_modules/@expo-google-fonts/<package>/<weight>/<Family>_<weight>.ttf). Read them with fs and pass them to Satori's `fonts` option; WOFF2 is not supported.",
            "Satori rules: flexbox only (no CSS grid); every element with more than one child needs display: 'flex'; set boxSizing: 'border-box' on the root; draw arrows, icons and symbols as inline SVG, not text glyphs (the fonts lack them, and emoji are unsupported).",
            "Design for email: 1200 px wide canvas (shown at 600 px), text readable at half size, strong contrast, solid background, one idea per graphic, all text in Spanish.",
        ].join("\n\n"),
        schema: z.object({
            path: z.string().describe("Where to write the file, relative to /home/user. Use 'generate.tsx' for the graphic script."),
            content: z.string().describe("Complete contents of the file (for generate.tsx: the full TypeScript source, which must write the rendered PNG to output.png)."),
        }),
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

export const editorTools = [getResearchFindings, generateImages, createChart, sandboxWriteFiles, sandboxCmdExec, sandboxRead, sandboxSaveImage, ...beehiivTools, ...notionTools];