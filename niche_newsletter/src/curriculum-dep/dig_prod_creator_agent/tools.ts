// Capabilities: create the digital products (code generation), spawn subagents, generate images
import { z } from "zod";
import { HumanMessage, tool, ToolMessage, type ToolRuntime } from "langchain";
import type { DigProdCreationAgentState } from "./state.js";
import { OpenRouter } from "@openrouter/sdk";
import { MODELS } from "../../models.js";
import { type ImageGenerationRequestAspectRatio } from "@openrouter/sdk/models";
import { Dropbox, DropboxResponseError } from "dropbox";
import { Command, INTERRUPT, isInterrupted } from "@langchain/langgraph";
import { Sandbox, CommandExitError } from "e2b";
import dotenv from 'dotenv';
import { readOrInitFile } from "../../shared/file_utils.js";
import { readFile } from "fs/promises";
import { getCanvaMCP } from "../../shared/canva_mcp.js";

export const KEEP_CANVA_TOOLS = new Set([   
    'export-design',
    'get-export-formats',
    'get-design',
    'get-design-pages',
    'get-design-content',
    'search-designs',
    'import-design-from-url',
    // 'copy-design',
    // 'create-design-from-brand-template',
    'upload-asset-from-url',
    // 'resize-design',
    // 'merge-designs',
    'start-editing-transaction',
    'perform-editing-operations',
    'commit-editing-transaction',
    'cancel-editing-transaction',
    // 'get-design-thumbnail',
    'search-brand-templates',
    'get-brand-template-dataset',
    "autofill-design",
    'resolve-shortlink',
    'get-assets',
    // 'list-brand-kits',
    'get-design-candidates',
]);

function toDirectDropboxUrl(shareUrl: string): string {
    const url = new URL(shareUrl);
    url.searchParams.delete("dl");
    url.searchParams.set("raw", "1");
    return url.toString();
}

// Shared by generate_image and create_document — both just need "these bytes, hosted at
// a public URL" and don't care about the Dropbox-specific mechanics to get there.
async function uploadToDropboxAndGetShareUrl(dropboxToken: string, path: string, contents: Buffer): Promise<string> {
    const dropbox = new Dropbox({ accessToken: dropboxToken });

    let uploadedPath: string;
    try {
        const uploadResult = await dropbox.filesUpload({
            path,
            contents,
            mode: { '.tag': 'overwrite' },
            mute: true,
        });
        uploadedPath = uploadResult.result.path_lower ?? path;
    } catch (error) {
        throw new Error(`Dropbox upload failed: ${error}`);
    }

    try {
        const shareResult = await dropbox.sharingCreateSharedLinkWithSettings({
            path: uploadedPath,
            settings: { audience: { '.tag': 'public' } },
        });
        return toDirectDropboxUrl(shareResult.result.url);
    } catch (error) {
        const existingUrl = (error instanceof DropboxResponseError
            ? (error.error as { shared_link_already_exists?: { metadata?: { url?: string } } })?.shared_link_already_exists?.metadata?.url
            : undefined);
        if (!existingUrl) throw new Error(`Dropbox share-link creation failed: ${error}`);
        return toDirectDropboxUrl(existingUrl);
    }
}

// Versions pinned to match this repo's own package.json, so scripts render the same way
// inside the sandbox as they would with the repo's own installed dependencies.
// The @expo-google-fonts packages supply the static TTFs that kit.tsx registers.
const REACT_PDF_SANDBOX_DEPS = "react@19.3.0 @react-pdf/renderer@4.9.0 tsx@4.23.13 @expo-google-fonts/inter@0.4.2 @expo-google-fonts/jetbrains-mono@0.4.1";
// Pre-built design components, written next to the agent's script so it can import "./kit.tsx".
const KIT_SOURCE = await readFile("src/curriculum-dep/dig_prod_creator_agent/kit.tsx", "utf-8");
const SANDBOX_TSCONFIG = JSON.stringify({
    compilerOptions: { jsx: "react-jsx", module: "esnext", moduleResolution: "bundler", esModuleInterop: true },
});
const SANDBOX_PACKAGE_JSON = JSON.stringify({ name: "doc-gen", private: true, type: "module" });

const createDocument = tool(
    async ({ fileName, code }, runtime: ToolRuntime<typeof DigProdCreationAgentState>) => {
        const e2bApiKey = process.env.E2B_API_KEY;
        if (!e2bApiKey) {
            return "E2B_API_KEY is not set — cannot run the document-generation sandbox.";
        }
        const dropboxToken = process.env.DROPBOX;
        if (!dropboxToken) {
            return "DROPBOX access token is not set — cannot host the generated document.";
        }

        const existingSandboxId = runtime.state.sandboxId;
        let sandbox: Sandbox | undefined;
        let isReconnect = false;
        try {
            if (existingSandboxId) {
                sandbox = await Sandbox.connect(existingSandboxId);
                isReconnect = true;
            } else {
                // 5 minutes covers a cold `npm install` plus the render; extended below
                // once the render succeeds, to give a reviewer time to look at it.
                sandbox = await Sandbox.create({ timeoutMs: 5 * 60_000 });
            }
        } catch (error) {
            return `Could not ${existingSandboxId ? "reconnect to" : "start"} the sandbox: ${error}`;
        }

        try {
            await sandbox.files.write([
                { path: "generate.tsx", data: code },
                { path: "images.json", data: JSON.stringify(runtime.state.images ?? {}) },
                { path: "kit.tsx", data: KIT_SOURCE },
                ...(isReconnect ? [] : [
                    { path: "tsconfig.json", data: SANDBOX_TSCONFIG },
                    { path: "package.json", data: SANDBOX_PACKAGE_JSON },
                ])
            ]);

            if (!isReconnect) {
                try {
                    await sandbox.commands.run(`npm install --no-audit --no-fund ${REACT_PDF_SANDBOX_DEPS}`, { timeoutMs: 180_000 });
                } catch (error) {
                    await sandbox.kill()
                    if (error instanceof CommandExitError) {
                        return `Sandbox dependency install failed:\n${error.stderr || error.stdout}`;
                    }
                    throw error;
                }
            }

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

            let pdfBytes: Uint8Array;
            try {
                pdfBytes = await sandbox.files.read("output.pdf", { format: "bytes" });
            } catch {
                return `Your script ran without error but never wrote "output.pdf" — call renderToFile(<YourDocument />, "output.pdf") at the end of it.`;
            }

            const name = fileName.toLowerCase().replace(/\s+/g, "_");
            const dropboxPath = `/newsletter_images/digital_products/${name}.pdf`;
            let documentUrl: string;
            try {
                documentUrl = await uploadToDropboxAndGetShareUrl(dropboxToken, dropboxPath, Buffer.from(pdfBytes));
            } catch (error) {
                return error instanceof Error ? error.message : `Failed to host the generated document: ${error}`;
            }

            // Give a reviewer room to look at the result before the sandbox auto-kills;
            // finalize_document kills it for real once a human approves.
            await sandbox.setTimeout(30 * 60_000);

            return new Command({
                update: {
                    sandboxId: sandbox.sandboxId,
                    pendingDocumentUrl: documentUrl,
                    messages: [
                        new ToolMessage({ content: [ 
                            {type: "text", text: `"${fileName}" rendered and hosted for review at ${documentUrl} — call finalize_document once you have reviewed the document (attached) and are content with the result.`},
                            ], tool_call_id: runtime.toolCallId }),
                        new HumanMessage({content: [
                            {type: "file", source_type: "base64", data: Buffer.from(pdfBytes).toString("base64"), mime_type: "application/pdf", metadata: { filename: `${name}.pdf` }}
                        ]})
                    ],
                },
            });
        } catch (error) {
            await sandbox.kill();
            return `Document generation failed: ${error}`;
        }
    }, {
        name: "create_document",
        description: `Render a PDF from a react-pdf (@react-pdf/renderer) TSX script, executed in an isolated E2B sandbox — not in this process — and host the draft on Dropbox for review. Call finalize_document afterwards to submit it.

"code" must be a complete, self-contained script that:
- builds the document from the design kit at "./kit.tsx" (written alongside your script). Import from it rather than styling from scratch:
  - Shell and pages: KitDocument({title, author}), CoverPage({eyebrow, title, subtitle, author, edition, imageUrl}), ContentPage({docTitle, brand}) (flows onto new pages, with a running header, footer and page numbers), ChecklistPage({docTitle, brand, title, intro, items: [{title, detail}]}), CTAPage({eyebrow, heading, body, buttonLabel, url, footnote}).
  - Blocks inside a ContentPage: SectionHeader({eyebrow, title, breakBefore}), H2, P, Lead, Strong (inline), Bullets({items}), Callout({tone: "note"|"tip"|"warning", title}), ExampleBlock({label}, children: string) (monospace, for prompts or templates), StatRow({stats: [{value, label}]}), Steps({steps: [{title, body}]}), Figure({src, caption, height}).
  - theme (colors, fonts "Inter" and "JetBrains Mono", sizes), for occasional custom Views that should still match the kit.
- ends by calling renderToFile(<YourDocument />, "output.pdf") — this exact call, this exact filename, or nothing comes back.
- to embed a previously generated image, reads images.json (written alongside your script) and looks up the entry by the fileName you gave generate_image, e.g.: JSON.parse(readFileSync("images.json", "utf-8"))["hero-banner"].imageUrl — don't guess a URL, look it up.

The sandbox only has react, @react-pdf/renderer, tsx, the kit's fonts, and Node's built-in modules available — no other npm packages. If finalize_document comes back rejected, call this again with fixed code — it reconnects to the same sandbox instead of starting over, so dependencies don't need reinstalling.`,
        schema: z.object({
            fileName: z.string().describe("Short name for the document — used for its Dropbox filename and as its key for later reference. Pass the same fileName to finalize_document."),
            code: z.string().describe("A complete, self-contained react-pdf TSX script — see the tool description for the exact contract it must follow."),
        }),
    }
);

const finalizeDocument = tool(
    async ({ fileName }, runtime: ToolRuntime<typeof DigProdCreationAgentState>) => {
        const sandboxId = runtime.state.sandboxId;
        const documentUrl = runtime.state.pendingDocumentUrl;
        if (!sandboxId || !documentUrl) {
            return "No pending render to finalize — call create_document first.";
        }

        try {
            await Sandbox.kill(sandboxId);
        } catch {
            // Not fatal — it may have already auto-killed on its own timeout; the
            // document is hosted regardless of whether the sandbox is still around.
        }

        const documents = {
            ...runtime.state.documents,
            [fileName]: documentUrl,
        };
        return new Command({
            update: {
                messages: [new ToolMessage({ content: `Document saved as "${fileName}": ${documentUrl}`, tool_call_id: runtime.toolCallId })],
                documents,
                sandboxId: undefined,
                pendingDocumentUrl: undefined,
            },
        });
    }, {
        name: "finalize_document",
        description: "Commit the pending document (already hosted on Dropbox by create_document) as final and tear down its sandbox. Gated behind human review — call this right after create_document succeeds. If the reviewer rejects it, the sandbox stays alive so create_document can reconnect and revise instead of starting over.",
        schema: z.object({
            fileName: z.string().describe("Same fileName you passed to create_document for this document."),
        }),
    }
);

const genImage = tool(
    async ({ prompt, aspectRatio, fileName }, runtime: ToolRuntime<typeof DigProdCreationAgentState>) => {
        const name = fileName.toLowerCase().replace(/\s+/g, "_");
        
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

        if (genResult instanceof ReadableStream) {
            return "Image generation unexpectedly returned a stream — this tool only supports non-streaming responses.";
        }

        const image = genResult.data?.[0];
        if (!image?.b64Json) {
            return "Image generation returned no image data.";
        }
        const imageBytes = Buffer.from(image.b64Json, "base64");
        const extension = image.mediaType?.split("/")[1] ?? "png";

        const dropboxPath = `/newsletter_images/digital_product_images/${name}.${extension}`;

        let shareUrl: string;
        try {
            shareUrl = await uploadToDropboxAndGetShareUrl(dropboxToken, dropboxPath, imageBytes);
        } catch (error) {
            return error instanceof Error ? error.message : `Failed to host the generated image: ${error}`;
        }
        const images = {
            ...runtime.state.images,
            [fileName]: { imageUrl: shareUrl, prompt },
        };
        return new Command({
            update: {
                messages: [new ToolMessage({ content: `Image saved as "${fileName}" — reference it by that name when building the document.`, tool_call_id: runtime.toolCallId })],
                images
            },
        });
    }, {
        name: "generate_image",
        description: "Generate an image from a text prompt via OpenRouter's image API and host it on Dropbox. Saved under fileName in state — every image generated this run stays available by name, not just the most recent one. Give each image a distinct fileName if you're generating more than one.",
        schema: z.object({
            prompt: z.string().describe("Detailed description of the image to generate"),
            aspectRatio: z.string().optional().default("16:9").describe("Aspect ratio, e.g. '16:9', '1:1', '4:3'"),
            fileName: z.string().describe("Short description of the image to use for filename.")
        }),
    }
);

const proposedDocumentContent = tool(
    async (runtime: ToolRuntime<typeof DigProdCreationAgentState>) => {
        const filePath = runtime.state.doc_content_path;
        return await readOrInitFile(filePath);
    }, {
        name: "read_proposed_document_content",
        description: "Use this at the beginning to get a good grasp of what the document should be about",
    }
)

const canvaTools = await getCanvaMCP(KEEP_CANVA_TOOLS);

export const productCreationTools = [genImage, createDocument, finalizeDocument, proposedDocumentContent, ...canvaTools];