// One-time interactive setup: authorizes this app against Notion's OAuth-gated remote MCP
// server and persists the resulting tokens locally, so `getNotionMCP()` (../notion_mcp.ts)
// can run unattended afterward, for any agent in any department that imports it — no
// browser needed on subsequent pipeline runs.
//
// Run by hand once: npx tsx src/shared/setups/notion_oauth_setup.ts
// Re-run only if the stored refresh token is later revoked or invalidated.

import { runInteractiveOAuthSetup } from "../mcp_oauth_setup.js";
import { FileBackedOAuthProvider } from "../mcp_oauth_provider.js";
import { NOTION_MCP_URL, NOTION_REDIRECT_URL, NOTION_TOKEN_STORE_PATH, NOTION_MCP_APP_NAME } from "../notion_mcp.js";

runInteractiveOAuthSetup({
    serverName: "notion",
    mcpUrl: NOTION_MCP_URL,
    redirectUrl: NOTION_REDIRECT_URL,
    tokenStorePath: NOTION_TOKEN_STORE_PATH,
    provider: new FileBackedOAuthProvider("notion", NOTION_REDIRECT_URL, NOTION_TOKEN_STORE_PATH, NOTION_MCP_APP_NAME),
}).catch((error) => {
    console.error(error);
    process.exit(1);
});
