// Minimal durable storage for one OAuth-protected MCP client's session state — dynamic
// client registration info, tokens, and the in-flight PKCE code verifier — so a headless
// process can complete the OAuth dance once, interactively, and reuse the resulting
// (refreshable) tokens on every subsequent unattended run without a browser.

import { readOrInitFile, writeFileEnsuringDir } from "./file_utils.js";

type OAuthStoredState<TClientInfo, TTokens> = {
    clientInformation?: TClientInfo;
    tokens?: TTokens;
    codeVerifier?: string;
};

export class FileOAuthStore<TClientInfo, TTokens> {
    constructor(private readonly filePath: string) {}

    private async read(): Promise<OAuthStoredState<TClientInfo, TTokens>> {
        const raw = await readOrInitFile(this.filePath, "{}");
        try {
            return JSON.parse(raw) as OAuthStoredState<TClientInfo, TTokens>;
        } catch {
            return {};
        }
    }

    private async write(state: OAuthStoredState<TClientInfo, TTokens>): Promise<void> {
        await writeFileEnsuringDir(this.filePath, JSON.stringify(state, null, 2));
    }

    async getClientInformation(): Promise<TClientInfo | undefined> {
        return (await this.read()).clientInformation;
    }

    async saveClientInformation(clientInformation: TClientInfo): Promise<void> {
        const state = await this.read();
        state.clientInformation = clientInformation;
        await this.write(state);
    }

    async getTokens(): Promise<TTokens | undefined> {
        return (await this.read()).tokens;
    }

    async saveTokens(tokens: TTokens): Promise<void> {
        const state = await this.read();
        state.tokens = tokens;
        await this.write(state);
    }

    async getCodeVerifier(): Promise<string | undefined> {
        return (await this.read()).codeVerifier;
    }

    async saveCodeVerifier(codeVerifier: string): Promise<void> {
        const state = await this.read();
        state.codeVerifier = codeVerifier;
        await this.write(state);
    }
}
