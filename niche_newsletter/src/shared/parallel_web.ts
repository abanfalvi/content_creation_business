import { z } from "zod";
import { tool } from "@langchain/core/tools";
import Parallel from "parallel-web";

export const parallelClient = new Parallel({ apiKey: process.env.PARALLEL_SEARCH_API_KEY });

export const webSearchSchema = z.object({
    queries: z.array(z.string()).min(1).describe("2-3 concise keyword search queries, 3-6 words each"),
    objective: z.string().optional().describe("Natural-language description of what you're trying to find — used together with queries to focus results on the most relevant content"),
    mode: z.enum(["turbo", "fast", "basic", "advanced"]).optional().default("fast").describe("turbo: fastest, lower quality. fast (default): high quality within a ~1s budget. basic: low latency, works best with 2-3 high-quality queries. advanced: highest quality, more retrieval/compression, higher latency."),
    maxResults: z.number().int().min(1).max(20).optional().describe("Max number of results to return"),
    includeDomains: z.array(z.string()).optional().describe("Only return results from these domains, e.g. [\"arxiv.org\", \"github.com\"]"),
});
export type WebSearchInput = z.infer<typeof webSearchSchema>;

export const WEB_SEARCH_DESCRIPTION = "Search the web via Parallel. Give 2-3 concise keyword queries (3-6 words each) plus a natural-language objective describing what you're actually trying to find — used together to focus results on what's relevant. Returns ranked results with URL, title, and relevant excerpts (not full page content — use extract_web_content once you've picked a URL worth reading in full).";

export async function runWebSearch({ queries, objective, mode, maxResults, includeDomains }: WebSearchInput) {
    const result = await parallelClient.search({
        search_queries: queries,
        objective: objective ?? null,
        mode: mode ?? null,
        advanced_settings: maxResults || includeDomains?.length
            ? {
                ...(maxResults ? { max_results: maxResults } : {}),
                ...(includeDomains?.length ? { source_policy: { include_domains: includeDomains } } : {}),
            }
            : null,
    });
    return result.results.map(r => ({
        url: r.url,
        title: r.title,
        publishDate: r.publish_date,
        excerpts: r.excerpts,
    }));
}

export const webSearchTool = tool(runWebSearch, {
    name: "web_search",
    description: WEB_SEARCH_DESCRIPTION,
    schema: webSearchSchema,
});

export const extractWebContentTool = tool(
    async ({ urls, objective, queries, fullContent }) => {
        const result = await parallelClient.extract({
            urls,
            objective: objective ?? null,
            search_queries: queries ?? null,
            advanced_settings: fullContent ? { full_content: true } : null,
        });
        return {
            results: result.results.map(r => ({
                url: r.url,
                title: r.title,
                publishDate: r.publish_date,
                excerpts: r.excerpts,
                fullContent: r.full_content,
            })),
            errors: result.errors,
        };
    }, {
        name: "extract_web_content",
        description: "Fetch and extract content from up to 20 specific URLs via Parallel — use once web_search (or another source) has surfaced a URL worth reading beyond its search excerpt, or when you already have a URL in hand. An objective/queries pair focuses the extracted excerpts on what's relevant rather than the whole page. Only set fullContent when excerpts genuinely aren't enough — it costs more latency and tokens.",
        schema: z.object({
            urls: z.array(z.string()).min(1).max(20).describe("URLs to extract content from (up to 20)"),
            objective: z.string().optional().describe("Natural-language description of what you're trying to find on these pages"),
            queries: z.array(z.string()).optional().describe("Optional keyword queries, used together with objective to focus excerpts"),
            fullContent: z.boolean().optional().describe("Set true to also get each result's full page content (markdown), truncated to a reasonable length — not just the relevant excerpts. Costs more latency and tokens."),
        }),
    }
);
