// Shared one-time interactive OAuth setup for an OAuth-gated remote MCP server — run by
// hand once per integration. Drives the MCP SDK's `auth()` orchestrator through discovery,
// dynamic client registration, browser authorization, and the token exchange, persisting
// the result via the given provider's own token store so the corresponding get*MCP()
// loader can run unattended afterward. Used by notion_oauth_setup.ts, beehiiv_oauth_setup.ts,
// and any future OAuth-gated MCP integration this project adds.

import { createServer } from "node:http";
import { auth } from "@modelcontextprotocol/sdk/client/auth.js";
import type { OAuthClientProvider } from "@modelcontextprotocol/sdk/client/auth.js";

function waitForAuthorizationCode(redirectUrl: string): Promise<string> {
    const port = Number(new URL(redirectUrl).port);
    return new Promise((resolve, reject) => {
        const server = createServer((req, res) => {
            const url = new URL(req.url ?? "/", `http://localhost:${port}`);
            const code = url.searchParams.get("code");
            const error = url.searchParams.get("error");

            if (error) {
                res.writeHead(400, { "Content-Type": "text/plain" });
                res.end(`Authorization failed: ${error}`);
                server.close();
                reject(new Error(`Authorization failed: ${error}`));
                return;
            }
            if (!code) {
                res.writeHead(400, { "Content-Type": "text/plain" });
                res.end("Missing authorization code.");
                return;
            }

            res.writeHead(200, { "Content-Type": "text/plain" });
            res.end("Authorized — you can close this tab.");
            server.close();
            resolve(code);
        });
        server.listen(port, () => {
            console.log(`Listening for the OAuth callback on ${redirectUrl} ...`);
        });
    });
}

export async function runInteractiveOAuthSetup(options: {
    serverName: string;
    mcpUrl: string;
    redirectUrl: string;
    tokenStorePath: string;
    provider: OAuthClientProvider;
}): Promise<void> {
    const { serverName, mcpUrl, redirectUrl, tokenStorePath, provider } = options;

    const initialResult = await auth(provider, { serverUrl: mcpUrl });
    if (initialResult === "AUTHORIZED") {
        console.log(`Already authorized for ${serverName} — existing saved tokens are still valid. Nothing to do.`);
        return;
    }

    console.log(`Waiting for you to complete ${serverName} authorization in the browser...`);
    const code = await waitForAuthorizationCode(redirectUrl);

    const finalResult = await auth(provider, { serverUrl: mcpUrl, authorizationCode: code });
    if (finalResult !== "AUTHORIZED") {
        throw new Error(`Unexpected authorization result for ${serverName}: ${finalResult}`);
    }

    console.log(`${serverName} authorized. Tokens saved to ${tokenStorePath} — its MCP loader will now work unattended.`);
}
