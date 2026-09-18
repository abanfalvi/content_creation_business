import { MultiServerMCPClient } from "@langchain/mcp-adapters";
import type { DynamicStructuredTool } from "langchain";
import dotenv from 'dotenv';
import { FileBackedOAuthProvider } from "../src/shared/mcp_oauth_provider.js";
import { CANVA_REDIRECT_URL, CANVA_TOKEN_STORE_PATH, SM_AGENT_APP_NAME } from "../src/distribution-dep/sm_agent/mcp.js";

async function getBufferTools(): Promise<DynamicStructuredTool[]> {

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
            url: "https://mcp.buffer.com/mcp",
            headers: {
                Authorization: `Bearer ${bufferToken}`
            },
        },
    });

    try {
        const tools = await client.getTools();
        console.log(tools.map(tool => tool.name))
        // return tools.filter(tool => KEEP_BUFFER_TOOLS.has(tool.name));
        return [];
    } catch (error) {
        console.error("Failed to load buffer MCP tools:", error);
        return [];
    }
};

async function getCanvaTools(): Promise<DynamicStructuredTool[]> {
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
            url: "https://mcp.canva.com/mcp",
            authProvider,
        },
    });

    try {
        const tools = await client.getTools();

        // console.log(tools.map(tool => tool.name))
        console.log(tools.map(tool => [tool.name, tool.description]))
        return [];
    } catch (error) {
        console.error("Failed to load canva MCP tools:", error);
        return [];
    }
};

async function getApifyTools(): Promise<DynamicStructuredTool[]> {

    const apifyToken = process.env.APIFY_API_KEY;
    if (!apifyToken) {
        console.warn(
            "No api key has been set for Apify tool"
        );
        return [];
    }

    const client = new MultiServerMCPClient({
        buffer: {
            transport: "http",
            url: "https://mcp.apify.com/",
            headers: {
                Authorization: `Bearer ${apifyToken}`
            },
        },
    });

    try {
        const tools = await client.getTools();
        console.log(tools.map(tool => tool.name))
        // return tools.filter(tool => KEEP_BUFFER_TOOLS.has(tool.name));
        return [];
    } catch (error) {
        console.error("Failed to load apify MCP tools:", error);
        return [];
    }
};

console.log(await getApifyTools());