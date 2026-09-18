// One-time interactive setup: authorizes this app against Canva's OAuth-gated remote MCP
// server and persists the resulting tokens locally, so `getCanvaTools()` (../mcp.js) can run
// unattended afterward — no browser needed on subsequent pipeline runs.
//
// Run by hand once: npx tsx src/distribution-dep/sm_agent/setups/canva_oauth_setup.ts
// Re-run only if the stored refresh token is later revoked or invalidated.

import { runInteractiveOAuthSetup } from "../../../shared/mcp_oauth_setup.js";
import { FileBackedOAuthProvider } from "../../../shared/mcp_oauth_provider.js";
import { CANVA_MCP_URL, CANVA_REDIRECT_URL, CANVA_TOKEN_STORE_PATH, SM_AGENT_APP_NAME } from "../mcp.js";

runInteractiveOAuthSetup({
    serverName: "canva",
    mcpUrl: CANVA_MCP_URL,
    redirectUrl: CANVA_REDIRECT_URL,
    tokenStorePath: CANVA_TOKEN_STORE_PATH,
    provider: new FileBackedOAuthProvider("canva", CANVA_REDIRECT_URL, CANVA_TOKEN_STORE_PATH, SM_AGENT_APP_NAME),
}).catch((error) => {
    console.error(error);
    process.exit(1);
});
