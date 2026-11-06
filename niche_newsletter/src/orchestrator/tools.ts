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
import { basename, extname, join, resolve, sep } from "path";
import { readFile } from "fs/promises";
import { applyFindAndReplace, appendFileEnsuringDir, readOrInitFile } from "../shared/file_utils.js";
import { getBeehiivMCP } from "../shared/beehiiv_mcp.js";
import { dataPaths } from "../shared/paths.js";
import { webSearchTool as webSearch, extractWebContentTool as extractWebContent } from "../shared/parallel_web.js";
import { saveIntoMemories } from "../shared/call_memory_agent.js";
import { streamAgents } from "../shared/progress_update.js";
import { isEvalMode, sideEffectLog } from "../shared/eval_guard.js";
import { addScheduledRun, cancelScheduledRun, listScheduledRuns, sanitizePrompt, type ScheduledRun } from "../shared/scheduled_runs.js";
import { evaluateAgentTraces } from "../../self_evolution/skill_evolution/llm_judges.js";
import { loadThreadTranscript } from "../../self_evolution/skill_evolution/trace_transcript.js";

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

    "list_publications",
    "list_posts",
    "get_post"
])

const slugifyTheme = (theme: string) => theme.toLowerCase().trim().replace(/\s+/g, "_");

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

const readResearchTopic = tool(
    async ({ fileTheme }) => {
        const path = join(dataPaths.researchScratchPad(), `${slugifyTheme(fileTheme)}_notes.md`);
        try {
            return await readFile(path, "utf-8");
        } catch {
            return `File theme (${fileTheme}) not found. Use list_research_topics to check what are available.`
        }
    }, {
        name: "read_research_topic",
        description: "Read the full content of the research notes for a topic. If the document has already a summary on top, the filter agent already worked on it.",
        schema: z.object({
            fileTheme: z.string().describe("Name of the topic you want to read, exactly as it is used in the file name"),
        }),
    }
);

const GUIDE_MAX_CHARS = 30_000;

async function readPromptingGuide(guidePath: string | undefined): Promise<string> {
    if (!guidePath?.trim()) return "";
    const root = resolve(dataPaths.managementNotes());
    const full = resolve(root, guidePath.trim().replace(/^[\\/]+/, ""));
    if (!full.startsWith(root + sep) || extname(full) !== ".md") {
        throw new Error(`promptingGuide must be a .md file inside the management notes folder (e.g. /post_outlines/<topic>.md), got "${guidePath}".`);
    }
    let text: string;
    try {
        text = await readFile(full, "utf-8");
    } catch {
        throw new Error(`No outline file at "${guidePath}". Write the outline with write_file first, then pass its path.`);
    }
    if (!text.trim()) throw new Error(`The outline file "${guidePath}" is empty.`);
    if (text.length > GUIDE_MAX_CHARS) throw new Error(`The outline file "${guidePath}" is ${text.length} characters; the limit is ${GUIDE_MAX_CHARS}.`);
    return text;
}

const callEditorManager = tool(
    async ({instruction, researchTopic, step, isNewsRoundup, promptingGuide}, runtime: ToolRuntime<AgentStateType>) => {
        const currentThreadId = runtime.config.configurable?.thread_id as string | undefined
        const threadId = `${currentThreadId}:editor_manager`
        const topic = researchTopic
            ? researchTopic.toLowerCase().replace(/[^a-z0-9]+/g, "_")
            : runtime.state.researchTopic;
        if (!topic) return "No active topic, provide researchTopic";
        // Passed as run context on every call (not checkpointed state): an omitted path means no outline, so one never leaks into a different post.
        const promptingContent = await readPromptingGuide(promptingGuide);
        const input = {messages: [new HumanMessage({content: JSON.stringify(instruction)})], researchTopic: topic, currentStep: "flexibleWorkflow", isNewsRoundup: isNewsRoundup}
        const result = await streamAgents(editorManagerAgent, "editor_manager", input, threadId, runtime, {promptingGuide: promptingContent});
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
            instruction: handoffContract,
            researchTopic: z.string().optional().describe("Keywords of the topic of research that is used for filename. Only pass it when starting a new newsletter issue, or when resuming an older one (copy its exact name from list_research_topics). Omit it to keep working on the current one: any other spelling creates a second notes file for the same issue"),
            step: z.enum(["flexibleWorkflow", "researchStep"]).describe("If a complete content creation pipeline needs to run, use researchStep (research agent -> filtering agent -> use case writer -> editor agent). If not all the specialists have to work on the issue, use flexibleWorkflow."),
            isNewsRoundup: z.boolean().describe("Whether this request or newsletter post is going to be about writing the weekly AI news roundup"),
            promptingGuide: z.string().optional().describe("Path of the markdown file holding the agreed detailed outline for a post on a prompting technique, as you wrote it with write_file (e.g. /post_outlines/few_shot_examples.md). The file's content is delivered to the editor agent directly, so don't paste the outline into the instruction. Pass it on every call about that post, including revisions; omit it for any other post")
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
            {messages: [new HumanMessage({content: JSON.stringify(instruction)})]},
            threadId,
            runtime
        );
        return result.messages.at(-1)?.content
    }, {
        name: "call_distribution_manager_agent",
        description: "Call this agent when you the newsletter post should be published on social media or new leads (large Instagram accounts in the newsletter's niche) should be found and logged in Notion, or when you need to know what is currently trending or popular on TikTok and Instagram reels in the niche (it searches by keyword/hashtag and can transcribe the top videos; read-only research). It never contacts anyone.",
        schema: z.object({
            instruction: handoffContract
        })
    }
);

const calDigProdCreationAgent = tool(
    async ({instruction, doc_content_strategy_name},  runtime: ToolRuntime<AgentStateType>) => {
        const { DigProdCreationAgent } = await import("../curriculum-dep/dig_prod_creator_agent/agent.js");
        const currentThreadId = runtime.config.configurable?.thread_id as string | undefined
        const threadId = `${currentThreadId}:digital_product_creation_agent`
        const fullPath = join(dataPaths.contentStrategy(), `${doc_content_strategy_name.toLocaleLowerCase().replace(" ", "_")}.md`)
        const result = await streamAgents(
            DigProdCreationAgent, 
            "digital_product_creation_agent",
            {messages: [new HumanMessage({content: JSON.stringify(instruction)})], doc_content_path: fullPath},
            threadId,
            runtime
        );
        try {
            const { checkpointer: curriculumCheckpointer } = await import("../curriculum-dep/checkpointer.js");
            const transcript = await loadThreadTranscript(curriculumCheckpointer, threadId)
            if (transcript) {
                await evaluateAgentTraces(transcript, "dig_prod_creator_agent", [], { department: "curriculum-dep" })
            }
        } catch (err) {
            console.warn("[skill-evals] scoring digital_product_creation_agent failed:", err)
        }

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
        const threadId = `${managerThreadId ?? "unknown"}:digital_product_creation_agent`;

        const result = await DigProdCreationAgent.invoke(
            new Command({ resume: reviewDecision }),
            { configurable: { thread_id: threadId } }
        );

        return result.messages.at(-1)?.content;
    }, {
        name: "send_review_answer_to_dig_prod_creation_agent",
        description: "Resume the digital product agent's paused document (paused when it tried to call finalize_document, for you to review the draft it already rendered and hosted) with your review decision. Approving lets it finalize the document as-is; rejecting sends it back with concrete feedback to revise the script and re-render before trying again.",
        schema: z.object({
            approved: z.boolean().describe("Whether to approve the pending document for rendering/hosting as-is"),
            feedback: z.string().optional().describe("Required when approved is false — concrete, specific feedback for the digital product agent to revise the document"),
        }),
    }
);


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

const describeRun = (r: ScheduledRun) =>
    ({ id: r.id, runAt: new Date(r.runAt).toString(), repeat: r.repeat, prompt: r.prompt });

const scheduleRun = tool(
    async ({ prompt: rawPrompt, runAt, delayMinutes, repeat }) => {
        let prompt: string;
        try {
            prompt = sanitizePrompt(rawPrompt);
        } catch (error) {
            return error instanceof Error ? error.message : String(error);
        }
        const now = new Date();
        if ((runAt === undefined) === (delayMinutes === undefined)) {
            return "Pass exactly one of runAt or delayMinutes.";
        }
        const when = runAt !== undefined ? new Date(runAt) : new Date(now.getTime() + delayMinutes! * 60_000);
        if (Number.isNaN(when.getTime())) return `Could not parse runAt "${runAt}". Use ISO 8601, e.g. 2026-10-07T09:00.`;
        if (when <= now) return `That time is in the past. The current time is ${now.toString()}.`;
        if (isEvalMode()) {
            sideEffectLog.push({ server: "task_scheduler", tool: "schedule_run", args: { prompt, runAt: when.toISOString(), repeat }, at: now.toISOString() });
            return { scheduled: { id: "eval-mock-run", runAt: when.toString(), repeat: repeat ?? "once", prompt } };
        }
        let run: ScheduledRun;
        try {
            run = addScheduledRun(prompt, when, repeat ?? "once");
        } catch (error) {
            return error instanceof Error ? error.message : String(error);
        }
        return { scheduled: describeRun(run), note: "Added to the schedule. A scheduled job on GitHub checks for due runs at fixed times and starts this one at the first check after the set time, so it can start later than asked. It runs headlessly in a cloud sandbox, so the PC doesn't need to be on. The session is not kept in the TUI's /sessions: the run's output goes to the GitHub Actions log, and anything it saves (notes, Notion, Dropbox) persists." };
    }, {
        name: "schedule_run",
        description: "Schedule a prompt to be run by you (the orchestrator) later, once or on a daily/weekly repeat. This adds it to the schedule, and a scheduled job on GitHub later starts a headless run in a fresh session in a cloud sandbox, with nobody watching and nobody able to answer questions or approve anything, so write the prompt as a complete, self-contained instruction. Only schedule a publish or outreach if the user already agreed to that concrete plan.",
        schema: z.object({
            prompt: z.string().describe("Self-contained instruction to run, including every detail you would need (topic, angle, constraints) since you won't have this conversation's context in mind"),
            runAt: z.string().optional().describe("When to run, ISO 8601 (e.g. 2026-10-07T09:00 — local time if no offset is given). Use instead of delayMinutes"),
            delayMinutes: z.number().optional().describe("Run this many minutes from now. Use instead of runAt"),
            repeat: z.enum(["once", "daily", "weekly"]).optional().describe("Repeat after the first run. Defaults to once"),
        }),
    }
);

const listScheduledRunsTool = tool(
    async () => ({ now: new Date().toString(), scheduled: listScheduledRuns().map(describeRun) }),
    {
        name: "list_scheduled_runs",
        description: "List the runs currently scheduled, soonest first, plus the current date and time (use it to work out runAt for schedule_run).",
    }
);

const cancelScheduledRunTool = tool(
    async ({ id }) => {
        if (isEvalMode()) {
            sideEffectLog.push({ server: "task_scheduler", tool: "cancel_scheduled_run", args: { id }, at: new Date().toISOString() });
            return `Cancelled scheduled run ${id}.`;
        }
        return cancelScheduledRun(id) ? `Cancelled scheduled run ${id}.` : `No scheduled run with id ${id}.`;
    }, {
        name: "cancel_scheduled_run",
        description: "Cancel a scheduled run and remove it from the schedule (all future repeats too). Get the id from list_scheduled_runs.",
        schema: z.object({ id: z.string().describe("Id of the scheduled run") }),
    }
);

// const alphaxivTools = await getAlphaxivTools();
const beehiivTools = await getBeehiivMCP(KEEP_BEEHIIV_TOOLS);

const allTools = [
    listResearchTopics,
    readResearchTopic,
    callEditorManager,
    callDistributionManager,
    calDigProdCreationAgent,
    sendAnswerToDigProdCreationAgent,
    webSearch,
    extractWebContent,
    callMemoryManageAgent,
    scheduleRun,
    listScheduledRunsTool,
    cancelScheduledRunTool,
    ...beehiivTools
];

// An unattended scheduled run (src/run_scheduled.ts sets these) gets a reduced toolset, so a prompt
// that was injected into a schedule can't do the most damaging things: it can never create or cancel
// schedules itself (no self-replicating runs), and it can only publish if the schedule was allowed to.
const UNATTENDED_BLOCKED_TOOLS = new Set(["schedule_run", "cancel_scheduled_run"]);
if (process.env.NL_SCHEDULED_RUN === "1" && process.env.NL_ALLOW_DISTRIBUTION !== "1") {
    UNATTENDED_BLOCKED_TOOLS.add("call_distribution_manager_agent");
}

export const orchestratorTools = process.env.NL_SCHEDULED_RUN === "1"
    ? allTools.filter((t) => !UNATTENDED_BLOCKED_TOOLS.has(t.name))
    : allTools;