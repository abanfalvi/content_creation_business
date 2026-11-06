// Capabilities: create the digital products (code generation), spawn subagents, generate images
import { z } from "zod";
import { HumanMessage, tool, ToolMessage, type ToolRuntime } from "langchain";
import type { DigProdCreationAgentState, AgentStateType } from "./state.js";
import { OpenRouter } from "@openrouter/sdk";
import { MODELS } from "../../models.js";
import { type ImageGenerationRequestAspectRatio } from "@openrouter/sdk/models";
import { type Dropbox, DropboxResponseError } from "dropbox";
import { getDropbox } from "../../shared/dropbox.js";
import { Command, INTERRUPT, isInterrupted } from "@langchain/langgraph";
import { Sandbox, CommandExitError } from "e2b";
import dotenv from 'dotenv';
import { readOrInitFile } from "../../shared/file_utils.js";
import { readFile } from "fs/promises";
import { getCanvaMCP } from "../../shared/canva_mcp.js";
import { uploadToDropboxAndGetShareUrl } from "../../shared/upload_to_dropbox.js";

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

// A fresh sandbox is bootstrapped once (config, design kit, dependencies); after that every tool
// call reuses it through the ID kept in agent state. If the old sandbox has expired (e.g. a
// reviewer took longer than its timeout) a fresh one replaces it and the tool says so, since
// the files written earlier are gone.
async function connectOrCreateSandbox(state: AgentStateType): Promise<{ sandbox: Sandbox; notice: string } | string> {
    const staleSandboxId = state.sandboxId;
    if (staleSandboxId) {
        try {
            const sandbox = await Sandbox.connect(staleSandboxId);
            // Images may have been generated since the last call; keep the lookup file current.
            await sandbox.files.write("images.json", JSON.stringify(state.images ?? {}));
            return { sandbox, notice: "" };
        } catch {
            // Expired or unreachable: fall through and start a fresh one.
        }
    }

    let sandbox: Sandbox;
    try {
        // 5 minutes covers a cold `npm install`; every tool call extends it afterwards.
        sandbox = await Sandbox.create({ timeoutMs: 5 * 60_000 });
    } catch (error) {
        return `Could not start the sandbox: ${error}`;
    }

    try {
        await sandbox.files.write([
            { path: "images.json", data: JSON.stringify(state.images ?? {}) },
            { path: "kit.tsx", data: KIT_SOURCE },
            { path: "tsconfig.json", data: SANDBOX_TSCONFIG },
            { path: "package.json", data: SANDBOX_PACKAGE_JSON },
        ]);
        await sandbox.commands.run(`npm install --no-audit --no-fund ${REACT_PDF_SANDBOX_DEPS}`, { timeoutMs: 180_000 });
    } catch (error) {
        await sandbox.kill().catch(() => {});
        if (error instanceof CommandExitError) {
            return `Sandbox dependency install failed:\n${error.stderr || error.stdout}`;
        }
        return `Sandbox setup failed: ${error}`;
    }

    const notice = staleSandboxId
        ? "NOTE: the previous sandbox had expired, so this is a fresh one — files you wrote earlier (such as generate.tsx) are gone; write them again.\n\n"
        : "";
    return { sandbox, notice };
}

// Every sandbox tool must return through this helper: the sandbox ID only reaches the agent
// state via a Command update, so a plain-string return would leave the next tool call unable
// to find the sandbox and it would start a fresh one.
function sandboxReply(sandbox: Sandbox, runtime: ToolRuntime<typeof DigProdCreationAgentState>, content: string) {
    return new Command({
        update: {
            sandboxId: sandbox.sandboxId,
            messages: [new ToolMessage({ content, tool_call_id: runtime.toolCallId })],
        },
    });
}

// Each call pushes the deadline out so the sandbox survives between the agent's steps.
const SANDBOX_IDLE_TIMEOUT_MS = 10 * 60_000;

const sandboxWriteFile = tool(
    async ({ path, content }, runtime: ToolRuntime<typeof DigProdCreationAgentState>) => {
        if (!process.env.E2B_API_KEY) {
            return "E2B_API_KEY is not set — cannot run the document-generation sandbox.";
        }
        const connection = await connectOrCreateSandbox(runtime.state);
        if (typeof connection === "string") return connection;
        const { sandbox, notice } = connection;
        await sandbox.setTimeout(SANDBOX_IDLE_TIMEOUT_MS);

        try {
            await sandbox.files.write([{ path, data: content }]);
            return sandboxReply(sandbox, runtime, `${notice}Saved ${path} in the sandbox. Run it with exec_cmd_sandboxed.`);
        } catch (error) {
            return sandboxReply(sandbox, runtime, `${notice}Could not write ${path}: ${error}`);
        }
    }, {
        name: "write_sandboxed_code",
        description: `Write a file into the document-generation sandbox (creating or overwriting it). Use it to save the react-pdf (@react-pdf/renderer) TSX script "generate.tsx" that builds your PDF. The sandbox is isolated from this process, persists between your calls, and is ready to use: dependencies are installed and the design kit is in place. Writing the script does not run it.

Workflow: write_sandboxed_code (path "generate.tsx") -> exec_cmd_sandboxed ("npx tsx generate.tsx") -> sandboxed_save_pdf -> finalize_document. To fix something, write the complete corrected file again and rerun; use read_sandboxed_code to look at what is currently there.

generate.tsx must be a complete, self-contained script that:
- builds the document from the design kit at "./kit.tsx" (already in the sandbox). Import from it rather than styling from scratch:
  - Shell and pages: KitDocument({title, author}), CoverPage({eyebrow, title, subtitle, author, edition, imageUrl}), ContentPage({docTitle, brand}) (flows onto new pages, with a running header, footer and page numbers), ChecklistPage({docTitle, brand, title, intro, items: [{title, detail}]}), CTAPage({eyebrow, heading, body, buttonLabel, url, footnote}).
  - Blocks inside a ContentPage: SectionHeader({eyebrow, title, breakBefore}), H2, P, Lead, Strong (inline), Bullets({items}), Callout({tone: "note"|"tip"|"warning", title}), ExampleBlock({label}, children: string) (monospace, for prompts or templates), StatRow({stats: [{value, label}]}), Steps({steps: [{title, body}]}), Figure({src, caption, height}).
  - theme (colors, fonts "Inter" and "JetBrains Mono", sizes), for occasional custom Views that should still match the kit.
- ends by calling renderToFile(<YourDocument />, "output.pdf") — this exact call, this exact filename, or sandboxed_save_pdf has nothing to publish.
- to embed a previously generated image, reads images.json (already in the sandbox, kept up to date) and looks up the entry by the fileName you gave generate_image, e.g.: JSON.parse(readFileSync("images.json", "utf-8"))["hero-banner"].imageUrl — don't guess a URL, look it up.

Don't overwrite kit.tsx, images.json, package.json or tsconfig.json. The sandbox only has react, @react-pdf/renderer, tsx, the kit's fonts, and Node's built-in modules — no other npm packages.`,
        schema: z.object({
            path: z.string().describe("Where to write the file, relative to /home/user. Use 'generate.tsx' for the document script."),
            content: z.string().describe("Complete contents of the file (for generate.tsx: the full react-pdf TSX source, ending with renderToFile(<YourDocument />, \"output.pdf\"))."),
        }),
    }
);

const sandboxCmdExec = tool(
    async ({ cmd }, runtime: ToolRuntime<typeof DigProdCreationAgentState>) => {
        if (!process.env.E2B_API_KEY) {
            return "E2B_API_KEY is not set — cannot run the document-generation sandbox.";
        }
        const connection = await connectOrCreateSandbox(runtime.state);
        if (typeof connection === "string") return connection;
        const { sandbox, notice } = connection;
        await sandbox.setTimeout(SANDBOX_IDLE_TIMEOUT_MS);

        try {
            const result = await sandbox.commands.run(cmd, { timeoutMs: 90_000 });
            return sandboxReply(sandbox, runtime, `${notice}Exit code 0.\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`);
        } catch (error) {
            if (error instanceof CommandExitError) {
                return sandboxReply(sandbox, runtime, `${notice}Command failed (exit code ${error.exitCode}).\nstdout:\n${error.stdout}\nstderr:\n${error.stderr}`);
            }
            // Timeouts and transport errors: report them rather than crash the agent run.
            return sandboxReply(sandbox, runtime, `${notice}Command did not complete: ${error}`);
        }
    }, {
        name: "exec_cmd_sandboxed",
        description: "Run a shell command in the document-generation sandbox and get back its exit code, stdout and stderr. The sandbox persists between your calls (files stay), and the working directory is /home/user. Typical uses: render the document with `npx tsx generate.tsx`; inspect the environment with `ls` or `pwd`; check that output.pdf exists. Dependencies are already installed, so don't run npm install. A command is stopped after 90 seconds. A non-zero exit code is returned as text, not an error: read stderr, fix the script with write_sandboxed_code, and run again. A script that runs cleanly still isn't published — call sandboxed_save_pdf for that.",
        schema: z.object({
            cmd: z.string().describe("Shell command to run from /home/user, e.g. 'npx tsx generate.tsx'"),
        }),
    }
);

const sandboxRead = tool(
    async ({ path }, runtime: ToolRuntime<typeof DigProdCreationAgentState>) => {
        if (!process.env.E2B_API_KEY) {
            return "E2B_API_KEY is not set — cannot run the document-generation sandbox.";
        }
        const connection = await connectOrCreateSandbox(runtime.state);
        if (typeof connection === "string") return connection;
        const { sandbox, notice } = connection;
        await sandbox.setTimeout(SANDBOX_IDLE_TIMEOUT_MS);

        try {
            const fileContent = await sandbox.files.read(path);
            return sandboxReply(sandbox, runtime, `${notice}${fileContent}`);
        } catch {
            const entries = await sandbox.files.list("/home/user");
            return sandboxReply(sandbox, runtime, `${notice}File not found: ${path}. Files in /home/user: ${entries.map(e => e.name).join(", ")}`);
        }
    }, {
        name: "read_sandboxed_code",
        description: "Read a text file from the document-generation sandbox (e.g. the generate.tsx you wrote earlier, to review or patch it, or images.json to see the available image URLs). Relative paths resolve against /home/user, the sandbox's working directory. If the file does not exist, the reply lists the files in /home/user so you can correct the path. Only for text files; to look at the rendered PDF, use sandboxed_save_pdf.",
        schema: z.object({
            path: z.string().describe("Path of the file to read, relative to /home/user (e.g. 'generate.tsx') or absolute"),
        }),
    }
);

const sandboxSavePdf = tool(
    async ({ fileName }, runtime: ToolRuntime<typeof DigProdCreationAgentState>) => {
        if (!process.env.E2B_API_KEY) {
            return "E2B_API_KEY is not set — cannot run the document-generation sandbox.";
        }
        const dropbox = getDropbox();
        if (typeof dropbox === "string") return dropbox;

        const connection = await connectOrCreateSandbox(runtime.state);
        if (typeof connection === "string") return connection;
        const { sandbox, notice } = connection;

        let pdfBytes: Uint8Array;
        try {
            pdfBytes = await sandbox.files.read("output.pdf", { format: "bytes" });
        } catch {
            const entries = await sandbox.files.list("/home/user");
            return sandboxReply(sandbox, runtime, `${notice}There is no "output.pdf" in /home/user — run generate.tsx first, and make sure it ends with renderToFile(<YourDocument />, "output.pdf"). Files in /home/user: ${entries.map(e => e.name).join(", ")}`);
        }

        const name = fileName.toLowerCase().replace(/\s+/g, "_");
        const dropboxPath = `/newsletter_images/digital_products/${name}.pdf`;
        let documentUrl: string;
        try {
            documentUrl = await uploadToDropboxAndGetShareUrl(dropbox, dropboxPath, Buffer.from(pdfBytes));
        } catch (error) {
            return sandboxReply(sandbox, runtime, `${notice}${error instanceof Error ? error.message : `Failed to host the generated document: ${error}`}`);
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
                        {type: "text", text: `${notice}"${fileName}" rendered and hosted for review at ${documentUrl} — call finalize_document once you have reviewed the document (attached) and are content with the result.`},
                        ], tool_call_id: runtime.toolCallId }),
                    new HumanMessage({content: [
                        {type: "file", source_type: "base64", data: Buffer.from(pdfBytes).toString("base64"), mime_type: "application/pdf", metadata: { filename: `${name}.pdf` }}
                    ]})
                ],
            },
        });
    }, {
        name: "sandboxed_save_pdf",
        description: [
            "Host the PDF your script rendered as a draft for review: reads /home/user/output.pdf from the sandbox, uploads it to Dropbox, and returns its URL together with the PDF attached so you can review it. It does not finalize anything.",
            "Call it after exec_cmd_sandboxed has run generate.tsx successfully. If output.pdf is missing, the reply lists the files in /home/user so you can see where the script wrote it.",
            "Look at the attached document before moving on. If anything is wrong (layout, copy, missing images), fix generate.tsx with write_sandboxed_code, rerun it with exec_cmd_sandboxed, and call this tool again with the same fileName. Once you are content, call finalize_document with that fileName.",
        ].join("\n\n"),
        schema: z.object({
            fileName: z.string().describe("Short name for the document — used for its Dropbox filename and as its key for later reference. Pass the same fileName to finalize_document."),
        }),
    }
);

const finalizeDocument = tool(
    async ({ fileName }, runtime: ToolRuntime<typeof DigProdCreationAgentState>) => {
        const sandboxId = runtime.state.sandboxId;
        const documentUrl = runtime.state.pendingDocumentUrl;
        if (!sandboxId || !documentUrl) {
            return "No pending render to finalize — call sandboxed_save_pdf first.";
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
        description: "Commit the pending document (already hosted on Dropbox by sandboxed_save_pdf) as final and tear down its sandbox. Gated behind human review — call this right after sandboxed_save_pdf succeeds. If the reviewer rejects it, the sandbox stays alive: fix generate.tsx with write_sandboxed_code, rerun it with exec_cmd_sandboxed, and call sandboxed_save_pdf again instead of starting over.",
        schema: z.object({
            fileName: z.string().describe("Same fileName you passed to sandboxed_save_pdf for this document."),
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
            shareUrl = await uploadToDropboxAndGetShareUrl(dropbox, dropboxPath, imageBytes);
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

export const productCreationTools = [genImage, sandboxWriteFile, sandboxCmdExec, sandboxRead, sandboxSavePdf, finalizeDocument, proposedDocumentContent, ...canvaTools];