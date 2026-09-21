import dotenv from 'dotenv';
import type { DynamicStructuredTool } from "@langchain/core/tools";
import { MultiServerMCPClient } from "@langchain/mcp-adapters";
import { FileBackedOAuthProvider } from "../../shared/mcp_oauth_provider.js";

dotenv.config();

export const SM_AGENT_APP_NAME = "niche-newsletter-sm-agent (canva)";

const KEEP_BUFFER_TOOLS = new Set([
    'get_account',
    'list_channels',
    'get_channel',
    'list_posts',
    'get_post',
    'create_post',
    'edit_post',
    // 'delete_post',
    'get_aggregated_post_metrics',
    'list_post_templates',
    'get_post_template',
    'create_post_template',
    'update_post_template',
    'delete_post_template',
]);

const KEEP_CANVA_TOOLS = new Set([
    // 'create-folder',
    // 'list-folder-items',
    // 'move-item-to-folder',
    // 'search-folders',
    'export-design',
    'get-export-formats',
    'get-design',
    'get-design-pages',
    'get-design-content',
    'search-designs',
    'import-design-from-url',
    'copy-design',
    // 'create-design-from-brand-template',
    'upload-asset-from-url',
    'resize-design',
    'merge-designs',
    'start-editing-transaction',
    'perform-editing-operations',
    'commit-editing-transaction',
    'cancel-editing-transaction',
    // 'get-design-thumbnail',
    // 'search-brand-templates',
    // 'get-brand-template-dataset',
    'resolve-shortlink',
    'get-assets',
    // 'list-brand-kits',
    'get-design-candidates',
]);

const BUFFER_MCP_URL = "https://mcp.buffer.com/mcp";
export const CANVA_MCP_URL = "https://mcp.canva.com/mcp";

export const CANVA_REDIRECT_URL = "http://localhost:8789/oauth/callback";
export const CANVA_TOKEN_STORE_PATH = "src/distribution-dep/sm_agent/.auth/canva_oauth.json";

export async function getBufferTools(): Promise<DynamicStructuredTool[]> {

    const bufferToken = process.env.BUFFER_API_KEY;
    if (!bufferToken) {
        console.warn(
            "No api key has been set for Buffer tool"
        );
        return [];
    }

    const client = new MultiServerMCPClient({
        buffer: {
            transport: "http",
            url: BUFFER_MCP_URL,
            headers: {
                Authorization: `Bearer ${bufferToken}`
            },
        },
    });

    try {
        const tools = await client.getTools();

        return tools.filter(tool => KEEP_BUFFER_TOOLS.has(tool.name));
    } catch (error) {
        console.error("Failed to load buffer MCP tools:", error);
        return [];
    }
};

export async function getCanvaTools(): Promise<DynamicStructuredTool[]> {
    const authProvider = new FileBackedOAuthProvider("canva", CANVA_REDIRECT_URL, CANVA_TOKEN_STORE_PATH, SM_AGENT_APP_NAME);

    const savedTokens = await authProvider.tokens();
    if (!savedTokens) {
        console.warn(
            "No saved Canva OAuth tokens found — skipping Canva MCP tools. Run the one-time setup once: " +
            "npx tsx src/distribution-dep/sm_agent/setups/canva_oauth_setup.ts"
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
        const tools = await client.getTools();

        return tools.filter(tool => KEEP_CANVA_TOOLS.has(tool.name));
    } catch (error) {
        console.error("Failed to load canva MCP tools:", error);
        return [];
    }
};