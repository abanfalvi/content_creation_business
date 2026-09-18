// One-time interactive setup: authorizes this app against Notion's OAuth-gated remote MCP
// server and persists the resulting tokens locally, so `getNotionMCP()` (mcp.ts) can run
// unattended afterward — no browser needed on subsequent pipeline runs.
//
// Run by hand once: npx tsx src/signal-editor-dep/editor_agent/notion_oauth_setup.ts
// Re-run only if the stored refresh token is later revoked or invalidated.

import { runInteractiveOAuthSetup } from "../../../shared/mcp_oauth_setup.js";
import { FileBackedOAuthProvider, NOTION_MCP_URL, NOTION_REDIRECT_URL, NOTION_TOKEN_STORE_PATH, EDITOR_AGENT_APP_NAME } from "../mcp.js";

runInteractiveOAuthSetup({
    serverName: "notion",
    mcpUrl: NOTION_MCP_URL,
    redirectUrl: NOTION_REDIRECT_URL,
    tokenStorePath: NOTION_TOKEN_STORE_PATH,
    provider: new FileBackedOAuthProvider("notion", NOTION_REDIRECT_URL, NOTION_TOKEN_STORE_PATH, EDITOR_AGENT_APP_NAME),
}).catch((error) => {
    console.error(error);
    process.exit(1);
});
