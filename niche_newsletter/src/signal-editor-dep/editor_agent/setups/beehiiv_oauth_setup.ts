// One-time interactive setup: authorizes this app against beehiiv's OAuth-gated remote MCP
// server and persists the resulting tokens locally, so `getBeehiivMCP()` (mcp.ts) can run
// unattended afterward — no browser needed on subsequent pipeline runs.
//
// Run by hand once: npx tsx src/signal-editor-dep/editor_agent/beehiiv_oauth_setup.ts
// Re-run only if the stored refresh token is later revoked or invalidated.

import { runInteractiveOAuthSetup } from "../../../shared/mcp_oauth_setup.js";
import { FileBackedOAuthProvider, BEEHIIV_MCP_URL, BEEHIIV_REDIRECT_URL, BEEHIIV_TOKEN_STORE_PATH } from "../mcp.js";

runInteractiveOAuthSetup({
    serverName: "beehiiv",
    mcpUrl: BEEHIIV_MCP_URL,
    redirectUrl: BEEHIIV_REDIRECT_URL,
    tokenStorePath: BEEHIIV_TOKEN_STORE_PATH,
    provider: new FileBackedOAuthProvider("beehiiv", BEEHIIV_REDIRECT_URL, BEEHIIV_TOKEN_STORE_PATH),
}).catch((error) => {
    console.error(error);
    process.exit(1);
});
