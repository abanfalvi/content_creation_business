import { Dropbox } from "dropbox";

let client: Dropbox | undefined;

// One Dropbox client for the whole process. With a refresh token the SDK checks the
// short-lived access token before every request and refreshes it when it has expired,
// so nothing needs to be replaced by hand. Get the refresh token once with
// `npx tsx src/shared/setups/dropbox_oauth_setup.ts`.
//
// Returns an error message instead of a client when Dropbox isn't configured, so tools
// can hand it straight back to the agent.
export function getDropbox(): Dropbox | string {
    if (client) return client;

    const { DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN, DROPBOX } = process.env;
    if (DROPBOX_APP_KEY && DROPBOX_APP_SECRET && DROPBOX_REFRESH_TOKEN) {
        client = new Dropbox({
            clientId: DROPBOX_APP_KEY,
            clientSecret: DROPBOX_APP_SECRET,
            refreshToken: DROPBOX_REFRESH_TOKEN,
        });
        return client;
    }
    // Legacy: a short-lived access token pasted into DROPBOX (expires after ~4 hours).
    if (DROPBOX) {
        client = new Dropbox({ accessToken: DROPBOX });
        return client;
    }
    return "Dropbox is not configured — set DROPBOX_APP_KEY, DROPBOX_APP_SECRET and DROPBOX_REFRESH_TOKEN (run `npx tsx src/shared/setups/dropbox_oauth_setup.ts` to get the refresh token).";
}
