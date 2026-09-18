// Add Beehiiv MCP. Notion MCP lives in ../../shared/notion_mcp.ts — it's used by agents
// in more than one department, not just this one.
import { MultiServerMCPClient } from "@langchain/mcp-adapters";
import type { DynamicStructuredTool } from "@langchain/core/tools";
import { FileBackedOAuthProvider } from "../../shared/mcp_oauth_provider.js";

// Re-exported so the existing setup script (beehiiv_oauth_setup.ts), which imports this
// from "../mcp.js", keeps working unchanged.
export { FileBackedOAuthProvider } from "../../shared/mcp_oauth_provider.js";

export const EDITOR_AGENT_APP_NAME = "niche-newsletter-editor-agent";

export const BEEHIIV_MCP_URL = "https://mcp.beehiiv.com/mcp";

// A different port from Notion's — both setup scripts could plausibly run close together
// (e.g. a fresh clone doing first-time setup for everything), and each needs its own local
// listener free to bind without colliding with the other.
export const BEEHIIV_REDIRECT_URL = "http://localhost:8788/oauth/callback";
export const BEEHIIV_TOKEN_STORE_PATH = "src/signal-editor-dep/editor_agent/.auth/beehiiv_oauth.json";

const KEEP_BEEHIIV_TOOLS = new Set([
    "edit_post",
    "edit_post_content",
    "edit_post_template",
    "edit_post_template_content",
    "get_post",
    "get_post_content",
    "get_post_footer",
    "get_post_template_content",
    "learn_post_authoring",
    "learn_post_metadata",
    "list_post_templates",
    "list_posts",
    "save_post",
    "save_post_footer",
    "save_post_template",
    "save_post_template_theme",
    "save_post_theme",
    "duplicate_post",
    "duplicate_post_template",
    "save_split_test",
    // Visuals/assets
    // "generate_image",
    "get_asset",
    // "get_image_generation_status",
    "list_assets",
    "save_file",
    "save_image",
    "update_asset",
    // Metadata
    "list_content_tags",
    "save_content_tag",
    // Self-service API discovery
    "read_documentation",
    "search_documentation",
])

// beehiiv's hosted remote MCP server is confirmed OAuth-only — a static bearer token
// gets an unauthorized error even with a valid beehiiv API key. FileBackedOAuthProvider
// (shared) implements the MCP SDK's OAuthClientProvider against a small local JSON file,
// so the interactive authorization step (run once, by hand, via `beehiiv_oauth_setup.ts`)
// is reused across every unattended pipeline run afterward — `tokens()`/`saveTokens()`
// are read and silently refreshed by the SDK's `auth()` helper, no browser needed after
// that first setup run. (Notion MCP follows the same pattern — see
// ../../shared/notion_mcp.ts.)

// Returns [] (rather than throwing) when the integration is unavailable — a missing
// token, an unreachable server, or an auth failure degrades this agent to running
// without beehiiv tools instead of failing agent startup entirely.
export async function getBeehiivMCP(): Promise<DynamicStructuredTool[]> {
    const authProvider = new FileBackedOAuthProvider("beehiiv", BEEHIIV_REDIRECT_URL, BEEHIIV_TOKEN_STORE_PATH, EDITOR_AGENT_APP_NAME);

    const savedTokens = await authProvider.tokens();
    if (!savedTokens) {
        console.warn(
            "No saved beehiiv OAuth tokens found — skipping beehiiv MCP tools. Run the one-time setup once: " +
            "npx tsx src/signal-editor-dep/editor_agent/beehiiv_oauth_setup.ts"
        );
        return [];
    }

    const client = new MultiServerMCPClient({
        beehiiv: {
            transport: "http",
            url: BEEHIIV_MCP_URL,
            authProvider,
        },
    });

    try {
        const tools = await client.getTools();

        return tools.filter(tool => KEEP_BEEHIIV_TOOLS.has(tool.name));
    } catch (error) {
        console.error("Failed to load beehiiv MCP tools:", error);
        return [];
    }
};
