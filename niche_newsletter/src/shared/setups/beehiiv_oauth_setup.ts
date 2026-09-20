// One-time interactive setup: authorizes this app against beehiiv's OAuth-gated remote MCP
// server and persists the resulting tokens locally, so `getBeehiivMCP()` (../beehiiv_mcp.ts)
// can run unattended afterward, for any agent in any department that imports it — no
// browser needed on subsequent pipeline runs.
//
// Run by hand once: npx tsx src/shared/setups/beehiiv_oauth_setup.ts
// Re-run only if the stored refresh token is later revoked or invalidated.

import { runInteractiveOAuthSetup } from "../mcp_oauth_setup.js";
import { FileBackedOAuthProvider } from "../mcp_oauth_provider.js";
import { BEEHIIV_MCP_URL, BEEHIIV_REDIRECT_URL, BEEHIIV_TOKEN_STORE_PATH, BEEHIIV_MCP_APP_NAME } from "../beehiiv_mcp.js";

runInteractiveOAuthSetup({
    serverName: "beehiiv",
    mcpUrl: BEEHIIV_MCP_URL,
    redirectUrl: BEEHIIV_REDIRECT_URL,
    tokenStorePath: BEEHIIV_TOKEN_STORE_PATH,
    provider: new FileBackedOAuthProvider("beehiiv", BEEHIIV_REDIRECT_URL, BEEHIIV_TOKEN_STORE_PATH, BEEHIIV_MCP_APP_NAME),
}).catch((error) => {
    console.error(error);
    process.exit(1);
});
