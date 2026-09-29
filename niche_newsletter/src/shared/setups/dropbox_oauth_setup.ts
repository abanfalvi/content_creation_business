// One-time interactive setup: exchanges a Dropbox authorization code for a long-lived
// refresh token, so `getDropbox()` (../dropbox.ts) can refresh its short-lived access
// tokens unattended instead of needing a new token pasted in every 4 hours.
//
// Needs DROPBOX_APP_KEY and DROPBOX_APP_SECRET in .env (App Console → your app → Settings).
// Prints DROPBOX_REFRESH_TOKEN to add to .env.
//
// Run by hand once: npx tsx src/shared/setups/dropbox_oauth_setup.ts
// Re-run only if the refresh token is revoked, or after changing the app's permissions.

import "dotenv/config";
import { createInterface } from "node:readline/promises";

const appKey = process.env.DROPBOX_APP_KEY;
const appSecret = process.env.DROPBOX_APP_SECRET;
if (!appKey || !appSecret) {
    console.error("Set DROPBOX_APP_KEY and DROPBOX_APP_SECRET in .env first.");
    process.exit(1);
}

// token_access_type=offline is what makes Dropbox issue a refresh token. No redirect_uri:
// Dropbox shows the code on the page for you to paste back here.
const authorizeUrl = new URL("https://www.dropbox.com/oauth2/authorize");
authorizeUrl.searchParams.set("client_id", appKey);
authorizeUrl.searchParams.set("response_type", "code");
authorizeUrl.searchParams.set("token_access_type", "offline");

console.log(`1. Open this URL and allow access:\n\n   ${authorizeUrl}\n`);
const rl = createInterface({ input: process.stdin, output: process.stdout });
const code = (await rl.question("2. Paste the authorization code here: ")).trim();
rl.close();

const response = await fetch("https://api.dropboxapi.com/oauth2/token", {
    method: "POST",
    body: new URLSearchParams({ grant_type: "authorization_code", code, client_id: appKey, client_secret: appSecret }),
});
const body = await response.json() as { refresh_token?: string; error_description?: string; error?: string };
if (!response.ok || !body.refresh_token) {
    console.error(`Token exchange failed: ${body.error_description ?? body.error ?? response.status}`);
    process.exit(1);
}

console.log(`\n3. Add this to .env:\n\nDROPBOX_REFRESH_TOKEN=${body.refresh_token}\n`);
