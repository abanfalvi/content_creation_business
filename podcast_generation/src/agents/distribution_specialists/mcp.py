import asyncio
import json
import os
from pathlib import Path

import webbrowser
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthClientMetadata, OAuthClientInformationFull, OAuthToken

TOKEN_CACHE_PATH = Path(".mcp_tokens.json")

CANVA_NOT_ALLOWED_TOOLS = [
    "generate-design", 
    "delete-folder", 
    "publish-brand-template",
    "comment-on-design",
    "list-comments",
    "list-replies",
    "reply-to-comment",
    # "create-design-from-candidate",
    # "search-brand-templates"
]
BUFFER_NOT_ALLOWED_TOOLS = [
    "get_account",
    "introspect_schema",
    "execute_query",
    "execute_mutation"
]


class FileTokenStorage(TokenStorage):
    async def get_tokens(self) -> OAuthToken | None:
        if not TOKEN_CACHE_PATH.exists():
            return None
        data = json.loads(TOKEN_CACHE_PATH.read_text()).get("tokens")
        return OAuthToken.model_validate(data) if data else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._write("tokens", tokens.model_dump(mode="json"))

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        if not TOKEN_CACHE_PATH.exists():
            return None
        data = json.loads(TOKEN_CACHE_PATH.read_text()).get("client_info")
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._write("client_info", client_info.model_dump(mode="json"))

    def _write(self, key: str, value: dict) -> None:
        data = json.loads(TOKEN_CACHE_PATH.read_text()) if TOKEN_CACHE_PATH.exists() else {}
        data[key] = value
        TOKEN_CACHE_PATH.write_text(json.dumps(data))


async def _redirect_handler(auth_url: str) -> None:
    print(f"Opening browser to authorize MCP access:\n{auth_url}")
    webbrowser.open(auth_url)


async def _callback_handler() -> tuple[str, str | None]:
    from aiohttp import web

    code_future: asyncio.Future[tuple[str, str | None]] = asyncio.get_event_loop().create_future()

    async def handle_callback(request: web.Request) -> web.Response:
        if not code_future.done():
            code_future.set_result((request.query.get("code"), request.query.get("state")))
        return web.Response(text="Authorized — you can close this tab.")

    app = web.Application()
    app.router.add_get("/callback", handle_callback)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", 8765)
    await site.start()
    try:
        return await code_future
    finally:
        await runner.cleanup()


def _make_mcp_auth(server_url: str) -> OAuthClientProvider:
    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="podcast_generation-distribution-agent",
            redirect_uris=["http://localhost:8765/callback"],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
        ),
        storage=FileTokenStorage(),
        redirect_handler=_redirect_handler,
        callback_handler=_callback_handler,
    )

async def get_canva_mcp():
    client = MultiServerMCPClient(
        {
            "canva": {
                "transport": "http", 
                "url": "https://mcp.canva.com/mcp",
                "auth": _make_mcp_auth(server_url="https://mcp.canva.com/mcp")
            }
        }
    )

    canva_tool = await client.get_tools()
    tools = [t for t in canva_tool if t.name not in CANVA_NOT_ALLOWED_TOOLS]
    return tools

async def get_buffer_mcp():
    client = MultiServerMCPClient(
        {
            "spotify": {
                "transport": "http",
                "url": "https://mcp.buffer.com/mcp",
                "headers": {
                    "Authorization": f"Bearer {os.getenv('BUFFER_API_KEY')}"
                }
            }
        }
    )

    spotify_tool = await client.get_tools()
    tools = [t for t in spotify_tool if t.name not in BUFFER_NOT_ALLOWED_TOOLS]
    return tools