// Shared beehiiv MCP integration — used by agents in more than one department (the
// signal/editor department's editor_agent, and others going forward). Lives here rather
// than under a single agent's folder so any department can import it without reaching
// across department boundaries. (Mirrors notion_mcp.ts's pattern.)

import { MultiServerMCPClient } from "@langchain/mcp-adapters";
import type { DynamicStructuredTool } from "@langchain/core/tools";
import { FileBackedOAuthProvider } from "./mcp_oauth_provider.js";
import { guardWriteTools, BEEHIIV_WRITE_TOOLS } from "./eval_guard.js";

export const BEEHIIV_MCP_APP_NAME = "niche-newsletter";

export const BEEHIIV_MCP_URL = "https://mcp.beehiiv.com/mcp";

// A different port from Notion's — both setup scripts could plausibly run close together
// (e.g. a fresh clone doing first-time setup for everything), and each needs its own local
// listener free to bind without colliding with the other.
export const BEEHIIV_REDIRECT_URL = "http://localhost:8788/oauth/callback";
export const BEEHIIV_TOKEN_STORE_PATH = "src/shared/.auth/beehiiv_oauth.json";

let beehiivToolsPromise: Promise<DynamicStructuredTool[]> | null = null;

// beehiiv's hosted remote MCP server is confirmed OAuth-only — a static bearer token
// gets an unauthorized error even with a valid beehiiv API key. FileBackedOAuthProvider
// (shared) implements the MCP SDK's OAuthClientProvider against a small local JSON file,
// so the interactive authorization step (run once, by hand, via
// `setups/beehiiv_oauth_setup.ts`) is reused across every unattended pipeline run
// afterward, by any agent that imports this module — `tokens()`/`saveTokens()` are read
// and silently refreshed by the SDK's `auth()` helper, no browser needed after that first
// setup run. (Notion MCP follows the same pattern — see notion_mcp.ts.)

// Returns [] (rather than throwing) when the integration is unavailable — a missing
// token, an unreachable server, or an auth failure degrades the calling agent to running
// without beehiiv tools instead of failing agent startup entirely.
export async function getBeehiivMCP(toolList: Set<string>): Promise<DynamicStructuredTool[]> {
    if (beehiivToolsPromise === null) {
        beehiivToolsPromise = (async () => {
            const authProvider = new FileBackedOAuthProvider("beehiiv", BEEHIIV_REDIRECT_URL, BEEHIIV_TOKEN_STORE_PATH, BEEHIIV_MCP_APP_NAME);
            const savedTokens = await authProvider.tokens();
            if (!savedTokens) {
                console.warn("No saved beehiiv OAuth tokens found — skipping beehiiv MCP tools. Run the one-time setup once: npx tsx src/shared/setups/beehiiv_oauth_setup.ts");
                return [];
            }
            const client = new MultiServerMCPClient({
                beehiiv: { transport: "http", url: BEEHIIV_MCP_URL, authProvider },
            });
            try {
                return await client.getTools();
            } catch (error) {
                console.error("Failed to load beehiiv MCP tools:", error);
                beehiivToolsPromise = null;
                return [];
            }
        })();
    }

    const tools = await beehiivToolsPromise;
    return guardWriteTools("beehiiv", tools.filter(tool => toolList.has(tool.name)), BEEHIIV_WRITE_TOOLS);
};
