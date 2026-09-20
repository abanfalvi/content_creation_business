import { MultiServerMCPClient } from "@langchain/mcp-adapters";
import type { DynamicStructuredTool } from "langchain";

const ALPHAXIV_MCP_URL = "https://api.alphaxiv.org/mcp/v1";

const KEEP_ALPHAXIV_TOOLS = new Set([
    "discover_papers",
    "get_paper_content",
    "answer_pdf_queries",
    "read_files_from_github_repository",
    "list_library",
    "save_papers_to_folder",
    "remove_papers_from_folder",
    "move_papers_between_folders",
    "create_folder",
    "rename_folder",
])

export async function getAlphaxivTools(): Promise<DynamicStructuredTool[]> {

    const alphaxivToken = process.env.ALPHAXIV_TOKEN;
    if (!alphaxivToken) {
        console.warn(
            "No api key has been set for Alphaxiv tool"
        );
        return [];
    }

    const client = new MultiServerMCPClient({
        buffer: {
            transport: "http",
            url: ALPHAXIV_MCP_URL,
            headers: {
                Authorization: `Bearer ${alphaxivToken}`
            },
        },
    });

    try {
        const tools = await client.getTools();

        return tools.filter(tool => KEEP_ALPHAXIV_TOOLS.has(tool.name));
    } catch (error) {
        console.error("Failed to load alphaxiv MCP tools:", error);
        return [];
    }
};