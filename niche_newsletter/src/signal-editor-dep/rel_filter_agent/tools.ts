import { z } from "zod";
import * as yaml from "js-yaml";
import { tool, type ToolRuntime } from "@langchain/core/tools";
import { readFile, writeFile } from 'fs/promises';
import { join } from 'path';
import { HumanMessage } from "@langchain/core/messages";
import { opikHandler } from "../../models.js";
import { RelFilterAgentState } from "./state.js";
import { researchAgent } from "../research_agent/agent.js"
import { newResearchRunId } from "../research_agent/shared_search_memory.js";
import { applyFindAndReplace } from "../../shared/file_utils.js";
import { dataPaths } from "../../shared/paths.js";
import { extractWebContentTool } from "../../shared/parallel_web.js";
import matter from "gray-matter";

const yamlString = z.string().refine((val) => {
    try {
        yaml.load(val);
        return true;
    } catch {
        return false;
    }
}, { message: "summary must be valid YAML" });

const readResearchFindings = tool(
    async (_input, runtime: ToolRuntime<typeof RelFilterAgentState>) => {
        const researchTopic = runtime.state.researchTopic
        const filePath = join(dataPaths.researchScratchPad(), `${researchTopic}_notes.md`)
        try {
            const findings = await readFile(filePath, "utf-8");
            return findings;
        } catch {
            return "No research findings for this topic yet"
        }
    }, {
        name: "read_research_findings",
        description: "Read what the research agent found"
    })

const editResearchFindings = tool(
    async ({to_replace, replace_with}, runtime: ToolRuntime<typeof RelFilterAgentState>) => {
        const researchTopic = runtime.state.researchTopic
        const filePath = join(dataPaths.researchScratchPad(), `${researchTopic}_notes.md`)

        try {
            const outcome = await applyFindAndReplace(filePath, to_replace, replace_with);
            if (outcome.status === "not_found") {
                return `"${to_replace}" not found in file (checked exact and whitespace-flexible matches).`;
            }
            if (outcome.status === "ambiguous") {
                return `"${to_replace}" found ${outcome.count} times — expected exactly one match, aborting edit. Add more context.`;
            }

            return "Successful edit";
        } catch (error) {
            return error
        }
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
        const filePath = join(dataPaths.researchScratchPad(), `${researchTopic}_notes.md`)
        const findings = matter(await readFile(filePath, "utf-8"));
        await writeFile(filePath, matter.stringify(findings.content, yaml.load(summary) as object));

    }, {
        name: "add_summaries",
        description: "Add summaries on the top of research findings to faster search in the future",
        schema: z.object({
            summary: yamlString
        })
    })

const callResearchAgent = tool(
    async ({ instruction }: { instruction: string }, runtime: ToolRuntime<typeof RelFilterAgentState>) => {
        const result = await researchAgent.invoke(
            {
                messages: [new HumanMessage(`${instruction} Current date: ${new Date().toDateString()}`)],
                researchTopic: runtime.state.researchTopic
            },
            { callbacks: [opikHandler], recursionLimit: 200, context: { agentId: "parent", researchRunId: newResearchRunId() } }
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

export const filteringTools = [readResearchFindings, editResearchFindings, addSummaries, extractWebContentTool, callResearchAgent];