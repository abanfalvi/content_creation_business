// Shared Notion MCP integration — used by agents in more than one department (the
// signal/editor department's editor_agent and the distribution department's
// user_outreach_agent, so far). Lives here rather than under a single agent's folder so
// any department can import it without reaching across department boundaries.

import { tool, type DynamicStructuredTool } from "@langchain/core/tools";
import { MultiServerMCPClient } from "@langchain/mcp-adapters";
import { FileBackedOAuthProvider } from "./mcp_oauth_provider.js";
import { guardWriteTools, NOTION_WRITE_TOOLS } from "./eval_guard.js";

export const NOTION_MCP_APP_NAME = "niche-newsletter";

export const NOTION_MCP_URL = "https://mcp.notion.com/mcp";
export const NOTION_REDIRECT_URL = "http://localhost:8787/oauth/callback";
export const NOTION_TOKEN_STORE_PATH = "src/shared/.auth/notion_oauth.json";

let notionToolsPromise: Promise<DynamicStructuredTool[]> | null = null;

// Notion's hosted remote MCP server is confirmed OAuth-only — a static bearer token gets
// a 403 ("Endpoint unavailable"). FileBackedOAuthProvider (shared) implements the MCP
// SDK's OAuthClientProvider against a small local JSON file, so the interactive
// authorization step (run once, by hand, via `setups/notion_oauth_setup.ts`) is reused
// across every unattended pipeline run afterward, by any agent that imports this module —
// `tokens()`/`saveTokens()` are read and silently refreshed by the SDK's `auth()` helper,
// no browser needed after that first setup run.

export type NotionParentGuard = {
    // Env vars holding the page ID(s) this agent may write under (e.g. "NOTION_DRAFT_PAGE").
    envVars: string[];
};

// Tools that place content under a parent, and where that parent sits in their arguments.
const PARENT_TOOL_ARGS: Record<string, string> = {
    "notion-create-pages": "parent",
    "notion-create-database": "parent",
    "notion-move-pages": "new_parent",
};

// Notion IDs show up dashed, undashed, in page URLs and in collection:// URLs.
function normalizeNotionId(value: unknown): string | undefined {
    if (typeof value !== "string") return undefined;
    return value.replace(/-/g, "").match(/[0-9a-f]{32}/i)?.[0].toLowerCase();
}

// The page a database/data source lives on: the first page in its fetched ancestor path,
// skipping the database/data-source entries in between. Undefined if the fetch failed or
// had no ancestor path.
async function owningPageOf(fetchTool: DynamicStructuredTool, id: string, isDataSource: boolean): Promise<string | undefined> {
    try {
        const result = await fetchTool.invoke({ id: isDataSource ? `collection://${id}` : id });
        let text = typeof result === "string" ? result : JSON.stringify(result);
        try { text = JSON.parse(text).text ?? text; } catch { /* already plain text */ }
        text = text.replace(/\\"/g, '"');
        const chain = text.match(/<ancestor-path>([\s\S]*?)<\/ancestor-path>/)?.[1] ?? "";
        for (const entry of chain.matchAll(/<(?:parent|ancestor-\d+)-(page|database|data-source) url="([^"]+)"/g)) {
            if (entry[1] === "page") return normalizeNotionId(entry[2]);
        }
    } catch (error) {
        console.warn(`[notion parent guard] fetch of ${id} failed: ${String(error)}`);
    }
    return undefined;
}

// Returns an error message for the agent when `parent` isn't allowed, or null when it is.
// Allowed: an allowlisted page itself, or a database (or data source) sitting directly on
// one. A page *inside* an allowlisted page is not allowed, so content can't nest.
async function checkParent(parent: any, allowed: Set<string>, fetchTool: DynamicStructuredTool | undefined, envVars: string[]): Promise<string | null> {
    const where = `the page set in ${envVars.join(" / ")}`;
    const refuse = (why: string) => `Refused: ${why}. All Notion content for this agent must go directly under ${where} (or a database sitting directly on it). Retry with that parent.`;

    if (allowed.size === 0) return `Refused: ${envVars.join(" / ")} is not set, so there is no permitted Notion location to write to.`;
    if (!parent || typeof parent !== "object") return refuse("no parent was given");

    if (parent.page_id !== undefined) {
        return allowed.has(normalizeNotionId(parent.page_id) ?? "") ? null : refuse("that parent page is not the permitted page");
    }

    const databaseId = normalizeNotionId(parent.database_id ?? parent.data_source_id);
    if (databaseId !== undefined) {
        if (!fetchTool) return refuse("the database's location couldn't be verified");
        const owner = await owningPageOf(fetchTool, databaseId, parent.data_source_id !== undefined);
        return owner !== undefined && allowed.has(owner) ? null : refuse("that database is not directly on the permitted page");
    }

    return refuse("the parent must be the permitted page or a database on it, not the workspace root");
}

function guardParents(selected: DynamicStructuredTool[], all: DynamicStructuredTool[], { envVars }: NotionParentGuard): DynamicStructuredTool[] {
    const fetchTool = all.find(t => t.name === "notion-fetch");
    // Ancestry doesn't change within a run, and a bulk lead run would otherwise re-fetch per row.
    const verified = new Map<string, string | null>();

    return selected.map((original) => {
        const parentArg = PARENT_TOOL_ARGS[original.name];
        if (!parentArg) return original;

        return tool(
            async (args: Record<string, unknown>) => {
                const allowed = new Set(envVars.map(name => normalizeNotionId(process.env[name])).filter((id): id is string => id !== undefined));
                const parent = args[parentArg];
                const key = JSON.stringify(parent ?? null);
                if (!verified.has(key)) verified.set(key, await checkParent(parent, allowed, fetchTool, envVars));
                const refusal = verified.get(key)!;
                if (refusal !== null) {
                    // Don't cache refusals: the agent may fix them by creating the database first.
                    verified.delete(key);
                    return refusal;
                }
                return original.invoke(args);
            },
            { name: original.name, description: original.description, schema: original.schema },
        ) as unknown as DynamicStructuredTool;
    });
}

// Returns [] (rather than throwing) when the integration is unavailable — a missing
// token, an unreachable server, or an auth failure degrades the calling agent to running
// without Notion tools instead of failing agent startup entirely. If Notion tools turn
// out to be load-bearing for a given agent's job rather than optional, that agent should
// treat an empty result as fatal itself rather than this loader throwing.
export async function getNotionMCP(toolList: Set<string>, parentGuard?: NotionParentGuard): Promise<DynamicStructuredTool[]> {
    if (notionToolsPromise === null) {
        notionToolsPromise = (async () => {
            const authProvider = new FileBackedOAuthProvider("notion", NOTION_REDIRECT_URL, NOTION_TOKEN_STORE_PATH, NOTION_MCP_APP_NAME);

            const savedTokens = await authProvider.tokens();
            if (!savedTokens) {
                console.warn(
                    "No saved Notion OAuth tokens found — skipping Notion MCP tools. Run the one-time setup once: " +
                    "npx tsx src/shared/setups/notion_oauth_setup.ts"
                );
                return [];
            }

            const client = new MultiServerMCPClient({
                notion: {
                    transport: "http",
                    url: NOTION_MCP_URL,
                    authProvider,
                },
            });

            try {
                return await client.getTools();
            } catch (error) {
                console.error("Failed to load Notion MCP tools:", error);
                notionToolsPromise = null
                return [];
            }
        })();
    }

    const tools = await notionToolsPromise;

    const selected = tools.filter(t => toolList.has(t.name));
    const parentGuarded = parentGuard ? guardParents(selected, tools, parentGuard) : selected;
    // Eval mode swaps the write tools for recorders after this, so the parent guard
    // only acts on real runs.
    return guardWriteTools("notion", parentGuarded, NOTION_WRITE_TOOLS);
};
