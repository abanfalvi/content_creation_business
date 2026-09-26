// One-time interactive setup: authorizes this app against Canva's OAuth-gated remote MCP
// server and persists the resulting tokens locally, so `getCanvaMCP()` (../canva_mcp.ts)
// can run unattended afterward, for any agent that imports it — no browser needed on
// subsequent pipeline runs.
//
// Run by hand once: npx tsx src/shared/setups/canva_oauth_setup.ts
// Re-run only if the stored refresh token is later revoked or invalidated.

import { runInteractiveOAuthSetup } from "../mcp_oauth_setup.js";
import { FileBackedOAuthProvider } from "../mcp_oauth_provider.js";
import { CANVA_MCP_URL, CANVA_REDIRECT_URL, CANVA_TOKEN_STORE_PATH, CANVA_MCP_APP_NAME } from "../canva_mcp.js";

runInteractiveOAuthSetup({
    serverName: "canva",
    mcpUrl: CANVA_MCP_URL,
    redirectUrl: CANVA_REDIRECT_URL,
    tokenStorePath: CANVA_TOKEN_STORE_PATH,
    provider: new FileBackedOAuthProvider("canva", CANVA_REDIRECT_URL, CANVA_TOKEN_STORE_PATH, CANVA_MCP_APP_NAME),
}).catch((error) => {
    console.error(error);
    process.exit(1);
});
