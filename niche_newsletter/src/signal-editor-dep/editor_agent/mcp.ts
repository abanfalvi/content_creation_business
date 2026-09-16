// Add Beehiiv and Notion MCP
import { MultiServerMCPClient } from "@langchain/mcp-adapters";
import type { DynamicStructuredTool } from "@langchain/core/tools";
import type { OAuthClientProvider } from "@modelcontextprotocol/sdk/client/auth.js";
import type {
    OAuthClientInformationMixed,
    OAuthClientMetadata,
    OAuthTokens,
} from "@modelcontextprotocol/sdk/shared/auth.js";
import { FileOAuthStore } from "../../shared/oauth_token_storage.js";

export const NOTION_MCP_URL = "https://mcp.notion.com/mcp";
export const BEEHIIV_MCP_URL = "https://mcp.beehiiv.com/mcp";

export const NOTION_REDIRECT_URL = "http://localhost:8787/oauth/callback";
export const NOTION_TOKEN_STORE_PATH = "src/signal-editor-dep/editor_agent/.auth/notion_oauth.json";

// A different port from Notion's — both setup scripts could plausibly run close together
// (e.g. a fresh clone doing first-time setup for everything), and each needs its own local
// listener free to bind without colliding with the other.
export const BEEHIIV_REDIRECT_URL = "http://localhost:8788/oauth/callback";
export const BEEHIIV_TOKEN_STORE_PATH = "src/signal-editor-dep/editor_agent/.auth/beehiiv_oauth.json";

const KEEP_NOTION_TOOLS = new Set([
    "notion-search",
    "notion-fetch",
    "notion-create-pages",
    "notion-update-page",
    "notion-move-pages",
    "notion-duplicate-page",
    "notion-list-private-pages",
    "notion-list-recent-pages",
    "notion-list-favorite-pages",
    "notion-create-database",
    "notion-update-data-source",
    "notion-create-view",
    "notion-update-view",
    "notion-create-attachment",
    "notion-create-file-upload",
    "notion-download-attachment",
    "notion-create-comment",
    "notion-get-comments",
    "notion-create-folder",
    "notion-update-folder",
    "notion-search-skills",
    "notion-convert-page-to-skill",
    "notion-get-users",
    "notion-get-async-task",
]);

const KEEP_BEEHIIV_TOOLS = new Set([
    // Post authoring — the agent's actual job
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

// Both Notion's and beehiiv's hosted remote MCP servers are confirmed OAuth-only — a
// static bearer token gets a 403 from Notion ("Endpoint unavailable") and an unauthorized
// error from beehiiv, even with a valid beehiiv API key. This implements the MCP SDK's
// OAuthClientProvider against a small local JSON file per server, so the interactive
// authorization step (run once, by hand, via `notion_oauth_setup.ts` / `beehiiv_oauth_setup.ts`)
// is reused across every unattended pipeline run afterward — `tokens()`/`saveTokens()` here
// are read and silently refreshed by the SDK's `auth()` helper, no browser needed after
// that first setup run.
export class FileBackedOAuthProvider implements OAuthClientProvider {
    private readonly store: FileOAuthStore<OAuthClientInformationMixed, OAuthTokens>;

    constructor(
        private readonly serverName: string,
        readonly redirectUrl: string,
        storagePath: string,
    ) {
        this.store = new FileOAuthStore(storagePath);
    }

    get clientMetadata(): OAuthClientMetadata {
        return {
            client_name: `niche-newsletter-editor-agent (${this.serverName})`,
            redirect_uris: [this.redirectUrl],
            grant_types: ["authorization_code", "refresh_token"],
            response_types: ["code"],
            token_endpoint_auth_method: "none",
        };
    }

    clientInformation() {
        return this.store.getClientInformation();
    }

    saveClientInformation(clientInformation: OAuthClientInformationMixed) {
        return this.store.saveClientInformation(clientInformation);
    }

    tokens() {
        return this.store.getTokens();
    }

    saveTokens(tokens: OAuthTokens) {
        return this.store.saveTokens(tokens);
    }

    async codeVerifier(): Promise<string> {
        const verifier = await this.store.getCodeVerifier();
        if (!verifier) {
            throw new Error(
                `No PKCE code verifier saved for ${this.serverName} — run the one-time OAuth setup script first.`
            );
        }
        return verifier;
    }

    saveCodeVerifier(codeVerifier: string) {
        return this.store.saveCodeVerifier(codeVerifier);
    }

    // Only reached during the one-time interactive setup (notion_oauth_setup.ts) — an
    // unattended pipeline run should always already have tokens saved, since getNotionMCP()
    // below checks for that before ever constructing a client.
    redirectToAuthorization(authorizationUrl: URL): void {
        console.log(`Open this URL in a browser to authorize ${this.serverName}:\n${authorizationUrl.toString()}`);
    }
}

// Returns [] (rather than throwing) when the integration is unavailable — a missing
// token, an unreachable server, or an auth failure degrades this agent to running
// without Notion tools instead of failing agent startup entirely. If Notion tools turn
// out to be load-bearing for this agent's job rather than optional, swap the `return []`
// in the catch (and the missing-token check) for a thrown error instead.
export async function getNotionMCP(): Promise<DynamicStructuredTool[]> {
    const authProvider = new FileBackedOAuthProvider("notion", NOTION_REDIRECT_URL, NOTION_TOKEN_STORE_PATH);

    const savedTokens = await authProvider.tokens();
    if (!savedTokens) {
        console.warn(
            "No saved Notion OAuth tokens found — skipping Notion MCP tools. Run the one-time setup once: " +
            "npx tsx src/signal-editor-dep/editor_agent/notion_oauth_setup.ts"
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
        const tools = await client.getTools()

        return tools.filter(tool => KEEP_NOTION_TOOLS.has(tool.name));
    } catch (error) {
        console.error("Failed to load Notion MCP tools:", error);
        return [];
    }
};

// Mirrors getNotionMCP() above — see the comment on FileBackedOAuthProvider for the
// reasoning (graceful [] on missing tokens or a failed connection, rather than throwing).
export async function getBeehiivMCP(): Promise<DynamicStructuredTool[]> {
    const authProvider = new FileBackedOAuthProvider("beehiiv", BEEHIIV_REDIRECT_URL, BEEHIIV_TOKEN_STORE_PATH);

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
