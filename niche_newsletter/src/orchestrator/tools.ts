// Capabilities: call the managers, design the content strategy with the user (curriculum roadmap, editorial direction)
import { z } from "zod";
import { tool, type ToolRuntime } from "@langchain/core/tools";
import { HumanMessage, ToolMessage } from "@langchain/core/messages";
import { Command, INTERRUPT, isInterrupted } from "@langchain/langgraph";
import { type AgentStateType, smPostRubric } from "./state.js";
import { getAlphaxivTools } from "./mcp.js";
import { editorManagerAgent } from "../signal-editor-dep/manager/manager.js";
import { distributionManagerAgent } from "../distribution-dep/manager/manager.js";
import { glob } from "glob";
import { basename, join } from "path";
import { applyFindAndReplace, appendFileEnsuringDir, readOrInitFile } from "../shared/file_utils.js";
import { getBeehiivMCP } from "../shared/beehiiv_mcp.js";
import { dataPaths } from "../shared/paths.js";
import { webSearchTool as webSearch, extractWebContentTool as extractWebContent } from "../shared/parallel_web.js";
import { saveIntoMemories } from "../shared/call_memory_agent.js";
import { streamAgents } from "../shared/progress_update.js";

function lastMessageContent(result: { messages: { content: unknown }[] }): string {
    const last = result.messages.at(-1);
    return typeof last?.content === "string" ? last.content : JSON.stringify(last?.content ?? "");
}

const KEEP_BEEHIIV_TOOLS = new Set([
    "get_automation_stats",
    "get_crawler_analytics",
    "get_post_stats",
    "get_post_stats_batch",
    "get_publication_stats",
    "get_website_analytics",
    "get_website_analytics_breakdown",
    "get_website_analytics_conditions_schema",

    "get_referral_program",
    "list_recommendations",

    "list_publications"
])

const handoffContract = z.object({
    task_id: z.string().describe("Unique id for this assignment"),
    objectives: z.array(z.string()).describe("What this call should accomplish"),
    constraints: z.array(z.string()).describe("What narrows the work — angle, source doc, what to leave out"),
    deliverables: z.array(z.string()).describe("What you expect back"),
});
type HandoffContract = z.infer<typeof handoffContract>;

const listResearchTopics = tool(
    async () => {
        const relFilePath = dataPaths.researchScratchPad();
        const relFiles = (await glob("**/*.md", { cwd: relFilePath })).map(p => basename(p, "_notes.md"))
        return relFiles

    }, {
        name: "list_research_topics",
        description: "Use this to get the list of research topics that have been executed previously to be able to keep working on it"
    }
)

const callEditorManager = tool(
    async ({instruction, researchTopic, step, isNewsRoundup}, runtime: ToolRuntime<AgentStateType>) => {
        const currentThreadId = runtime.config.configurable?.thread_id as string | undefined
        const threadId = `${currentThreadId}:editor_manager`
        const topic = researchTopic
            ? researchTopic.toLowerCase().replace(/[^a-z0-9]+/g, "_")
            : runtime.state.researchTopic;
        if (!topic) throw new Error("No active topic, provide researchTopic");
        const input = {messages: [new HumanMessage({content: instruction})], researchTopic: topic, currentStep: "flexibleWorkflow", isNewsRoundup: isNewsRoundup}
        const result = await streamAgents(editorManagerAgent, "editor_manager", input, threadId, runtime);
        return new Command({
            update: {
                messages: [new ToolMessage({content: lastMessageContent(result), tool_call_id: runtime.toolCallId})],
                researchTopic: topic,
            }
        })
    }, {
        name: "call_editor_manager_agent",
        description: "Call this agent when you want to create a newsletter post, or any other documents",
        schema: z.object({
            instruction: z.string().describe("What the manager should do"),
            researchTopic: z.string().describe("Keywords of the topic of research that is used for filename. Only pass it when starting a new newsletter issue. Omit it to keep working on the current one"),
            step: z.enum(["flexibleWorkflow", "researchStep"]).describe("If a complete content creation pipeline needs to run, use researchStep (research agent -> filtering agent -> use case writer -> editor agent). If not all the specialists have to work on the issue, use flexibleWorkflow."),
            isNewsRoundup: z.boolean().describe("Whether this request or newsletter post is going to be about writing the weekly AI news roundup")
        })
    }
);

const callDistributionManager = tool(
    async ({instruction}, runtime: ToolRuntime<AgentStateType>) => {
        const currentThreadId = runtime.config.configurable?.thread_id as string | undefined
        const threadId = `${currentThreadId}:distribution_manager`
        const result = await streamAgents(
            distributionManagerAgent, 
            "distribution_manager",
            {messages: [new HumanMessage({content: instruction})]},
            threadId,
            runtime
        );
        return result.messages.at(-1)?.content
    }, {
        name: "call_distribution_manager_agent",
        description: "Call this agent when you the newsletter post should be published on social media or new leads should be found/contacted.",
        schema: z.object({
            instruction: z.string().describe("What the manager should do")
        })
    }
);

const calDigProdCreationAgent = tool(
    async ({instruction, doc_content_strategy_name},  runtime: ToolRuntime<AgentStateType>) => {
        const { DigProdCreationAgent } = await import("../curriculum-dep/dig_prod_creator_agent/agent.js");
        const currentThreadId = runtime.config.configurable?.thread_id as string | undefined
        const threadId = `${currentThreadId}:dig_prod_creation_agent`
        const fullPath = join(dataPaths.contentStrategy(), `${doc_content_strategy_name.toLocaleLowerCase().replace(" ", "_")}.md`)
        const result = await streamAgents(
            DigProdCreationAgent, 
            "digital_product_creation_agent",
            {messages: [new HumanMessage({content: JSON.stringify(instruction)})], doc_content_path: fullPath},
            threadId,
            runtime
        );
        return new Command({
            update: {
                messages: [new ToolMessage({content: lastMessageContent(result), tool_call_id: runtime.toolCallId})],
                sandboxId: result.sandboxId,
            }
        })
    }, {
        name: "call_dig_prod_creation_agent",
        description: "Call this agent when you want to create digital products",
        schema: z.object({
            doc_content_strategy_name: z.string().describe("filename of the document containing what the created document should be about"),
            instruction: handoffContract
        })
    }
);

const sendAnswerToDigProdCreationAgent = tool(
    async (reviewDecision: { approved: boolean; feedback?: string }, runtime: ToolRuntime<AgentStateType>) => {
        const { DigProdCreationAgent } = await import("../curriculum-dep/dig_prod_creator_agent/agent.js");
        const managerThreadId = runtime.config.configurable?.thread_id as string | undefined
        const threadId = `${managerThreadId ?? "unknown"}:dig_prod_creation_agent`;

        const result = await DigProdCreationAgent.invoke(
            new Command({ resume: reviewDecision }),
            { configurable: { thread_id: threadId } }
        );

        return result.messages.at(-1)?.content;
    }, {
        name: "send_review_answer_to_dig_prod_creation_agent",
        description: "Resume the digital product agent's paused document (paused when it tried to call create_document, for you to review the pending code/args) with your review decision. Approving lets it actually render and host the document as-is; rejecting sends it back with concrete feedback to revise before trying again.",
        schema: z.object({
            approved: z.boolean().describe("Whether to approve the pending document for rendering/hosting as-is"),
            feedback: z.string().optional().describe("Required when approved is false — concrete, specific feedback for the digital product agent to revise the document"),
        }),
    }
);



// const slugifyTheme = (theme: string) => theme.toLowerCase().trim().replace(/\s+/g, "_");

// const listContentStrategyThemes = tool(
//     async () => {
//         const files = await glob("*.md", { cwd: dataPaths.contentStrategy() });
//         if (files.length === 0) return "No content strategy themes exist yet.";

//         return Promise.all(files.map(async (file) => {
//             const theme = basename(file, ".md");
//             const content = await readOrInitFile(join(dataPaths.contentStrategy(), file));
//             const preview = content.split("\n").find(line => line.trim().length > 0)?.trim() ?? "";
//             return { theme, preview };
//         }));
//     }, {
//         name: "list_content_strategy_themes",
//         description: "List the existing content strategy themes (one markdown file per theme), each with a one-line preview. Use this to see what strategy docs already exist before reading, editing, or creating one.",
//     }
// );

// const readContentStrategy = tool(
//     async ({ theme }) => {
//         const path = join(dataPaths.contentStrategy(), `${slugifyTheme(theme)}.md`);
//         return await readOrInitFile(path);
//     }, {
//         name: "read_content_strategy",
//         description: "Read the full content strategy document for a theme. If the theme doesn't exist yet, this creates it (empty) rather than erroring — check list_content_strategy_themes first if you're not sure it exists.",
//         schema: z.object({
//             theme: z.string().describe("Theme name, e.g. 'AI productivity tools' — matched to its file by slugifying (lowercased, spaces to underscores)"),
//         }),
//     }
// );

// const editContentStrategy = tool(
//     async ({ theme, to_replace, replace_with }) => {
//         const path = join(dataPaths.contentStrategy(), `${slugifyTheme(theme)}.md`);
//         const outcome = await applyFindAndReplace(path, to_replace, replace_with);

//         if (outcome.status === "not_found") {
//             return `"${to_replace}" not found in the "${theme}" strategy doc (checked exact and whitespace-flexible matches).`;
//         }
//         if (outcome.status === "ambiguous") {
//             return `"${to_replace}" found ${outcome.count} times in the "${theme}" strategy doc — expected exactly one match, aborting edit.`;
//         }
//         return outcome.result;
//     }, {
//         name: "edit_content_strategy",
//         description: "Edit a theme's content strategy document by replacing one exact, unique substring with another. Requires an exact, unique match — if it reports no match or more than one, add more surrounding context and try again. To add brand-new content rather than changing existing text, use add_to_content_strategy instead.",
//         schema: z.object({
//             theme: z.string().describe("Theme this edit applies to"),
//             to_replace: z.string().describe("Exact text to replace"),
//             replace_with: z.string().describe("Text to replace it with"),
//         }),
//     }
// );

// const addToContentStrategy = tool(
//     async ({ theme, content }) => {
//         const path = join(dataPaths.contentStrategy(), `${slugifyTheme(theme)}.md`);
//         await appendFileEnsuringDir(path, content);
//         return `Added to the "${theme}" strategy doc.`;
//     }, {
//         name: "add_to_content_strategy",
//         description: "Append new content to a theme's content strategy document — creates the theme's file if it doesn't exist yet. Use this for adding new strategy notes; use edit_content_strategy to change something already there.",
//         schema: z.object({
//             theme: z.string().describe("Theme to add content under — a new theme file is created if it doesn't exist yet"),
//             content: z.string().describe("Content to append"),
//         }),
//     }
// );

const SEARCH_CONTEXT_LINES = 2;
const SEARCH_MAX_MATCHES = 20;

const searchContentStrategy = tool(
    async ({ query }) => {
        const files = await glob("*.md", { cwd: dataPaths.contentStrategy() });
        const needle = query.toLowerCase();
        const matches: { theme: string; line: number; snippet: string }[] = [];

        for (const file of files) {
            if (matches.length >= SEARCH_MAX_MATCHES) break;
            const theme = basename(file, ".md");
            const content = await readOrInitFile(join(dataPaths.contentStrategy(), file));
            const lines = content.split("\n");

            for (let i = 0; i < lines.length; i++) {
                if (matches.length >= SEARCH_MAX_MATCHES) break;
                if (!lines[i]!.toLowerCase().includes(needle)) continue;

                const start = Math.max(0, i - SEARCH_CONTEXT_LINES);
                const end = Math.min(lines.length, i + SEARCH_CONTEXT_LINES + 1);
                matches.push({ theme, line: i + 1, snippet: lines.slice(start, end).join("\n") });
            }
        }

        if (matches.length === 0) return `No matches for "${query}" across ${files.length} theme doc(s).`;
        return matches;
    }, {
        name: "search_content_strategy",
        description: `Full-text search across every content strategy theme doc for a keyword or phrase (case-insensitive substring match). Returns up to ${SEARCH_MAX_MATCHES} matches, each with the theme, line number, and a few lines of surrounding context — use this instead of reading every theme doc individually when you're looking for something specific.`,
        schema: z.object({
            query: z.string().describe("Keyword or phrase to search for"),
        }),
    }
);

const callMemoryManageAgent = tool(
    async ({whatToSave}, runtime: ToolRuntime<AgentStateType>) => {
        const messages = runtime.state.messages;
        return await saveIntoMemories(whatToSave, messages);
    }, {
        name: "call_memory_management_agent",
        description: "Save lessons, decisions, and user preferences worth keeping beyond this conversation to long-term memory. Not for content strategy.",
        schema: z.object({
            whatToSave: z.array(z.string()).describe("List of short descriptions from the interactions that should be saved for long-term")
        })
    }
);

// const alphaxivTools = await getAlphaxivTools();
const beehiivTools = await getBeehiivMCP(KEEP_BEEHIIV_TOOLS);

export const orchestratorTools = [
    listResearchTopics,
    callEditorManager,
    callDistributionManager,
    calDigProdCreationAgent,
    sendAnswerToDigProdCreationAgent,
    webSearch,
    extractWebContent,
    callMemoryManageAgent,
    ...beehiivTools
];