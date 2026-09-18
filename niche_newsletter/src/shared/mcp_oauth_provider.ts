// Shared OAuthClientProvider for OAuth-gated remote MCP servers — file-backed, so the
// interactive setup step (run once, by hand, via a per-server `*_oauth_setup.ts` script)
// persists tokens that the corresponding get*MCP()/get*Tools() loader can then reuse
// unattended. Any agent adding a new OAuth-only MCP integration should import this
// instead of re-implementing OAuthClientProvider.

import type { OAuthClientProvider } from "@modelcontextprotocol/sdk/client/auth.js";
import type {
    OAuthClientInformationMixed,
    OAuthClientMetadata,
    OAuthTokens,
} from "@modelcontextprotocol/sdk/shared/auth.js";
import { FileOAuthStore } from "./oauth_token_storage.js";

export class FileBackedOAuthProvider implements OAuthClientProvider {
    private readonly store: FileOAuthStore<OAuthClientInformationMixed, OAuthTokens>;

    constructor(
        private readonly serverName: string,
        readonly redirectUrl: string,
        storagePath: string,
        private readonly appName: string = "niche-newsletter",
    ) {
        this.store = new FileOAuthStore(storagePath);
    }

    get clientMetadata(): OAuthClientMetadata {
        return {
            client_name: `${this.appName} (${this.serverName})`,
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

    // Only reached during the one-time interactive setup script — an unattended pipeline
    // run should always already have tokens saved, since the loader checks for that before
    // ever constructing an MCP client.
    redirectToAuthorization(authorizationUrl: URL): void {
        console.log(`Open this URL in a browser to authorize ${this.serverName}:\n${authorizationUrl.toString()}`);
    }
}
