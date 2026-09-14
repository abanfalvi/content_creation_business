import { z } from "zod";
import * as yaml from "js-yaml";
import { tool, type ToolRuntime } from "@langchain/core/tools";
import { readFile, writeFile } from 'fs/promises';
import { join } from 'path';
import { HumanMessage } from "@langchain/core/messages";
import { opikHandler } from "../../models.js";
import { RelFilterAgentState } from "./state.js";
import { tavily } from "@tavily/core";
import { researchAgent } from "../research_agent/agent.js"

const yamlString = z.string().refine((val) => {
    try {
        yaml.load(val);
        return true;
    } catch {
        return false;
    }
}, { message: "summary must be valid YAML" });

// Normalize CRLF to LF so a to_replace written with \n still matches a Windows-line-ended file.
const normalizeNewlines = (s: string) => s.replace(/\r\n/g, "\n");

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// Any of these count as "the same quote" for matching purposes — scraped web content
// commonly uses curly/smart quotes where a model writes straight ones, or vice versa.
const SINGLE_QUOTES = `'‘’‚‛`;
const DOUBLE_QUOTES = `"“”„‟`;
const SINGLE_QUOTE_CLASS = `[${SINGLE_QUOTES}]`;
const DOUBLE_QUOTE_CLASS = `[${DOUBLE_QUOTES}]`;

// Collapses runs of whitespace in the target into `\s+`, and any quote character into
// a class matching all straight/curly variants, so indentation/line-break differences
// and quote-style mismatches between what the model wrote and the file's actual
// content don't block an otherwise-correct match.
const buildFlexiblePattern = (s: string) =>
    new RegExp(
        escapeRegExp(s)
            .replace(new RegExp(`[${SINGLE_QUOTES}]`, "g"), SINGLE_QUOTE_CLASS)
            .replace(new RegExp(`[${DOUBLE_QUOTES}]`, "g"), DOUBLE_QUOTE_CLASS)
            .replace(/\s+/g, "\\s+"),
        "g"
    );

// Tries an exact substring match first (fast, unambiguous); if that finds nothing,
// falls back to a whitespace-tolerant regex match before giving up.
function findAndReplace(content: string, to_replace: string, replace_with: string):
    | { status: "ok"; result: string }
    | { status: "not_found" }
    | { status: "ambiguous"; count: number } {
    const exactCount = content.split(to_replace).length - 1;
    if (exactCount === 1) {
        return { status: "ok", result: content.replaceAll(to_replace, replace_with) };
    }
    if (exactCount > 1) {
        return { status: "ambiguous", count: exactCount };
    }

    const flexiblePattern = buildFlexiblePattern(to_replace);
    const flexCount = content.match(flexiblePattern)?.length ?? 0;
    if (flexCount === 0) {
        return { status: "not_found" };
    }
    if (flexCount > 1) {
        return { status: "ambiguous", count: flexCount };
    }
    return { status: "ok", result: content.replace(flexiblePattern, replace_with) };
}


const readResearchFindings = tool(
    async (_input, runtime: ToolRuntime<typeof RelFilterAgentState>) => {
        const researchTopic = runtime.state.researchTopic
        const filePath = join("src/signal-editor-dep/research_agent/scratch_pad/", `${researchTopic}_notes.md`)
        const findings = await readFile(filePath, "utf-8")
        return findings;
    }, {
        name: "read_research_findings",
        description: "Read what the research agent found"
    })

const editResearchFindings = tool(
    async ({to_replace, replace_with}, runtime: ToolRuntime<typeof RelFilterAgentState>) => {
        const researchTopic = runtime.state.researchTopic
        const filePath = join("src/signal-editor-dep/research_agent/scratch_pad/", `${researchTopic}_notes.md`)
        const findings = normalizeNewlines(await readFile(filePath, "utf-8"))
        const to_replace_normalized = normalizeNewlines(to_replace);
        const replace_with_normalized = normalizeNewlines(replace_with);

        const outcome = findAndReplace(findings, to_replace_normalized, replace_with_normalized);
        if (outcome.status === "not_found") {
            return `"${to_replace}" not found in file (checked exact and whitespace-flexible matches).`;
        }
        if (outcome.status === "ambiguous") {
            return `"${to_replace}" found ${outcome.count} times — expected exactly one match, aborting edit. Add more context.`;
        }

        try {
            await writeFile(filePath, outcome.result, 'utf-8');
        } catch (error) {
            return error
        }

        return "Successful edit";
    }, {
        name: "edit_research_findings",
        description: "Trim the research findings to what is relevant",
        schema: z.object({
            to_replace: z.string(),
            replace_with: z.string()
        })
    })

const addSummaries = tool(
    async ({summary}, runtime: ToolRuntime<typeof RelFilterAgentState>) => {
        const researchTopic = runtime.state.researchTopic
        const filePath = join("src/signal-editor-dep/research_agent/scratch_pad/", `${researchTopic}_notes.md`)
        const findings = await readFile(filePath, "utf-8")
        await writeFile(filePath, summary + findings)

    }, {
        name: "add_summaries",
        description: "Add summaries on the top of research findings to faster search in the future",
        schema: z.object({
            summary: yamlString
        })
    })

const extractContent = tool(
    async ({ url }: { url: string[] }) => {
        const tvly = tavily();
        const response = await tvly.extract(url);

        const sections = response.results.map(r =>
            `## ${r.title ?? r.url}\nSource: ${r.url}\n\n${r.rawContent}`
        );

        if (response.failedResults.length > 0) {
            sections.push(
                `## Failed to extract\n` +
                response.failedResults.map(f => `- ${f.url}: ${f.error}`).join("\n")
            );
        }

        return sections.join("\n\n---\n\n");
    }, {
        name: "extract_web_content",
        description: "Check the content of the sources the research agent found",
        schema: z.object({
            url: z.array(z.string())
        })
    }
)

const callResearchAgent = tool(
    async ({ instruction }: { instruction: string }, runtime: ToolRuntime<typeof RelFilterAgentState>) => {
        const result = await researchAgent.invoke(
            {
                messages: [new HumanMessage(`${instruction} Current date: ${new Date().toDateString()}`)],
                researchTopic: runtime.state.researchTopic
            },
            { callbacks: [opikHandler], recursionLimit: 100 }
        );
        return result.messages.at(-1)?.content
    }, {
        name: "call_research_agent",
        description: "Call the research agent if there is a potential gap in the research to be filled",
        schema: z.object({
            instruction: z.string()
        })
    }
);

export const filteringTools = [readResearchFindings, editResearchFindings, addSummaries, extractContent, callResearchAgent];