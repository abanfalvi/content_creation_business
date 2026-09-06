import os

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

BUFFER_NOT_ALLOWED_TOOLS = [
    "introspect_schema",
    "execute_query",
    "execute_mutation"
]

async def get_buffer_mcp():
    client = MultiServerMCPClient(
        {
            "buffer": {
                "transport": "http",
                "url": "https://mcp.buffer.com/mcp",
                "headers": {
                    "Authorization": f"Bearer {os.getenv('BUFFER_API_KEY')}"
                }
            }
        }
    )

    buffer_tool = await client.get_tools()
    tools = [t for t in buffer_tool if t.name not in BUFFER_NOT_ALLOWED_TOOLS]
    return tools