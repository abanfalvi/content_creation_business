// Shared Notion MCP integration — used by agents in more than one department (the
// signal/editor department's editor_agent and the distribution department's
// user_outreach_agent, so far). Lives here rather than under a single agent's folder so
// any department can import it without reaching across department boundaries.

import type { DynamicStructuredTool } from "@langchain/core/tools";
import { MultiServerMCPClient } from "@langchain/mcp-adapters";
import { FileBackedOAuthProvider } from "./mcp_oauth_provider.js";

export const NOTION_MCP_APP_NAME = "niche-newsletter";

export const NOTION_MCP_URL = "https://mcp.notion.com/mcp";
export const NOTION_REDIRECT_URL = "http://localhost:8787/oauth/callback";
export const NOTION_TOKEN_STORE_PATH = "src/shared/.auth/notion_oauth.json";

// Notion's hosted remote MCP server is confirmed OAuth-only — a static bearer token gets
// a 403 ("Endpoint unavailable"). FileBackedOAuthProvider (shared) implements the MCP
// SDK's OAuthClientProvider against a small local JSON file, so the interactive
// authorization step (run once, by hand, via `setups/notion_oauth_setup.ts`) is reused
// across every unattended pipeline run afterward, by any agent that imports this module —
// `tokens()`/`saveTokens()` are read and silently refreshed by the SDK's `auth()` helper,
// no browser needed after that first setup run.

// Returns [] (rather than throwing) when the integration is unavailable — a missing
// token, an unreachable server, or an auth failure degrades the calling agent to running
// without Notion tools instead of failing agent startup entirely. If Notion tools turn
// out to be load-bearing for a given agent's job rather than optional, that agent should
// treat an empty result as fatal itself rather than this loader throwing.
export async function getNotionMCP(toolList: Set<string>): Promise<DynamicStructuredTool[]> {
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
        const tools = await client.getTools();

        return tools.filter(tool => toolList.has(tool.name));
    } catch (error) {
        console.error("Failed to load Notion MCP tools:", error);
        return [];
    }
};
