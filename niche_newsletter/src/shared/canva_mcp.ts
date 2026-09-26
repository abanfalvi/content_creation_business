// Shared Canva MCP integration — used by the distribution department's sm_agent, and
// available to any other department (e.g. curriculum's digital product creator) without
// reaching across department boundaries. Each caller passes its own tool allowlist.

import type { DynamicStructuredTool } from "@langchain/core/tools";
import { MultiServerMCPClient } from "@langchain/mcp-adapters";
import { FileBackedOAuthProvider } from "./mcp_oauth_provider.js";

// Kept as the name the existing OAuth client was registered under, so moving this module
// doesn't force a re-authorization.
export const CANVA_MCP_APP_NAME = "niche-newsletter-sm-agent (canva)";

export const CANVA_MCP_URL = "https://mcp.canva.com/mcp";
export const CANVA_REDIRECT_URL = "http://localhost:8789/oauth/callback";
export const CANVA_TOKEN_STORE_PATH = "src/shared/.auth/canva_oauth.json";

let canvaToolsPromise: Promise<DynamicStructuredTool[]> | null = null;

// Returns [] (rather than throwing) when the integration is unavailable, so the calling
// agent degrades to running without Canva tools instead of failing startup.
export async function getCanvaMCP(toolList: Set<string>): Promise<DynamicStructuredTool[]> {
    if (canvaToolsPromise === null) {
        canvaToolsPromise = (async () => {
            const authProvider = new FileBackedOAuthProvider("canva", CANVA_REDIRECT_URL, CANVA_TOKEN_STORE_PATH, CANVA_MCP_APP_NAME);

            const savedTokens = await authProvider.tokens();
            if (!savedTokens) {
                console.warn(
                    "No saved Canva OAuth tokens found — skipping Canva MCP tools. Run the one-time setup once: " +
                    "npx tsx src/shared/setups/canva_oauth_setup.ts"
                );
                return [];
            }

            const client = new MultiServerMCPClient({
                canva: {
                    transport: "http",
                    url: CANVA_MCP_URL,
                    authProvider,
                },
            });

            try {
                return await client.getTools();
            } catch (error) {
                console.error("Failed to load Canva MCP tools:", error);
                canvaToolsPromise = null;
                return [];
            }
        })();
    }

    const tools = await canvaToolsPromise;

    return tools.filter(tool => toolList.has(tool.name));
};
