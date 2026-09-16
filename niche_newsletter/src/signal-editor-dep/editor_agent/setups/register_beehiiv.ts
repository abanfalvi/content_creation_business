import { readFile, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import * as crypto from "node:crypto";
const REGISTER_URL = "https://mcp.beehiiv.com/register";
const AUTHORIZE_URL = "https://mcp.beehiiv.com/authorize";
const TOKEN_URL = "https://mcp.beehiiv.com/token";
const RESOURCE = "https://mcp.beehiiv.com/mcp";
const REDIRECT_URI = "http://localhost:8788/oauth/callback";
const CLIENT_FILE = ".beehiiv-client.json";
const TOKEN_FILE = ".beehiiv-tokens.json";

function makePkce() {
    const verifier = crypto.randomBytes(64).toString("base64url");
    const challenge = crypto.createHash("sha256").update(verifier).digest("base64url");
    return { verifier, challenge };
}

async function getClientId(): Promise<string> {
    try {
        const saved = JSON.parse(await readFile(CLIENT_FILE, "utf8"));
        if (saved.client_id) return saved.client_id;
    } catch { /* not registered yet */ }

    const resp = await fetch(REGISTER_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            client_name: "editor_agent",
            redirect_uris: [REDIRECT_URI],
            grant_types: ["authorization_code", "refresh_token"],
            response_types: ["code"],
            token_endpoint_auth_method: "none",
        })
    });
    if (!resp.ok) {
        throw new Error(`register failed: ${resp.status} ${await resp.text()}`);
    }
    const client = await resp.json();
    await writeFile(CLIENT_FILE, JSON.stringify(client, null, 2));
    return client.client_id;
}

function waitForCallback(): Promise<string> {
    return new Promise((resolve, reject) => {
        const server = createServer((req, res) => {
        const url = new URL(req.url!, "http://localhost");
        const code = url.searchParams.get("code");
        const err = url.searchParams.get("error");
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end(code
            ? "<h1>Authorized — you can close this tab.</h1>"
            : `<h1>Auth failed: ${err}</h1>`);
        server.close();
        if (code) resolve(code);
        else reject(new Error(`OAuth error: ${err} (${url.searchParams.get("error_description")})`));
        });
        server.on("error", reject);
        server.listen(8788, () => console.log("Listening for callback on :8788"));
    });
}


async function main() {
    const clientId = await getClientId();
    const { verifier, challenge } = makePkce();
    const state = crypto.randomBytes(16).toString("base64url");
    const authUrl = new URL(AUTHORIZE_URL);
    authUrl.searchParams.set("response_type", "code");
    authUrl.searchParams.set("client_id", clientId);
    authUrl.searchParams.set("redirect_uri", REDIRECT_URI);
    authUrl.searchParams.set("scope", "read write");
    authUrl.searchParams.set("state", state);
    authUrl.searchParams.set("code_challenge", challenge);
    authUrl.searchParams.set("code_challenge_method", "S256");
    authUrl.searchParams.set("resource", RESOURCE);   // required by beehiiv (RFC 8707)
    console.log("\nOpening browser for authorization...\n");
    console.log("If it didn't open, paste this into your browser:\n\n" + authUrl + "\n");
    const callbackPromise = waitForCallback();
    const code = await callbackPromise;

    const tokenResp = await fetch(TOKEN_URL, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
            grant_type: "authorization_code",
            code,
            redirect_uri: REDIRECT_URI,
            client_id: clientId,
            code_verifier: verifier,
            resource: RESOURCE,
        })
    });
    if (!tokenResp.ok) {
        throw new Error(`token exchange failed: ${tokenResp.status} ${await tokenResp.text()}`);
    }
    const tokens = await tokenResp.json();
    await writeFile(TOKEN_FILE, JSON.stringify(tokens, null, 2));
    }
main().catch((e) => {
    console.error(e);
    process.exit(1);
});