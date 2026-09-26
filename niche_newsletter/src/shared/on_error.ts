import {
    type ToolCallRequest
} from "langchain";

// MCP servers write their error text for the model (e.g. "post_id not found"), so unlike
// other errors it's passed on — trimmed, since some servers return long payloads.
const MCP_DETAIL_LIMIT = 1500;
const clip = (text: string) => (text.length > MCP_DETAIL_LIMIT ? `${text.slice(0, MCP_DETAIL_LIMIT)}…` : text);

// @langchain/mcp-adapters wraps every MCP failure in a ToolException whose message is
// either the server's own error ("returned an error: …") or the stringified transport
// error ("Error calling tool …: McpError: MCP error -32602: …"); the original error
// object isn't kept, so the message is all there is to classify.
function onMcpError(toolName: string, message: string): string {
    const serverError = message.match(/returned an error: ([\s\S]*)$/);
    if (serverError) {
        return `Tool '${toolName}' was rejected by its server: ${clip(serverError[1]!.trim())}\nFix the arguments based on this message before calling it again; don't repeat the same call.`;
    }

    const rpcCode = Number(message.match(/MCP error (-\d+)/)?.[1]);
    switch (rpcCode) {
        case -32602: return `Tool '${toolName}' failed: invalid arguments. ${clip(message)}\nCheck the tool's schema and fix the arguments before calling it again.`;
        case -32601: return `Tool '${toolName}' failed: the server doesn't offer this tool. Use a different tool.`;
        case -32001: return `Tool '${toolName}' failed: the server timed out. You may retry once; if it fails again, continue without it.`;
        case -32000: return `Tool '${toolName}' failed: the connection to its server closed. You may retry once; if it fails again, continue without it.`;
    }

    const httpStatus = Number(message.match(/Streamable HTTP error: .*?(\d{3})/)?.[1]);
    if (/Unauthorized|invalid_token|invalid_grant/i.test(message) || httpStatus === 401 || httpStatus === 403) {
        return `Tool '${toolName}' failed: its server rejected our authorization. Don't retry — tell the user the integration needs to be re-authorized.`;
    }
    if (httpStatus === 429) return `Tool '${toolName}' failed: rate limited by its server, try again later.`;
    if (httpStatus >= 500) return `Tool '${toolName}' failed: its server had an internal error (${httpStatus}). You may retry once.`;

    // Invalid arguments caught by the adapter's own schema check (a prettified ZodError)
    if (/✖|Invalid input|expected .* received/i.test(message)) {
        return `Tool '${toolName}' failed: invalid arguments.\n${clip(message)}\nFix the arguments before calling it again.`;
    }
    return `Tool '${toolName}' failed: ${clip(message)}`;
}

export function onRetry(error: unknown, request: ToolCallRequest): string | undefined {
    const toolName = request.toolCall.name;
    const err = error as Partial<NodeJS.ErrnoException> & { status?: number; statusCode?: number };

    if (error instanceof Error && error.name === "ToolException") {
        return onMcpError(toolName, error.message);
    }

    // Node filesystem errors (readFile/writeFile/mkdir/appendFile) carry a string `.code`
    // (MCP/JSON-RPC errors use numeric codes and are handled above)
    if (typeof err?.code === "string") {
        switch (err.code) {
            case "ENOENT":
                return `Tool '${toolName}' failed: a required file was not found.`;
            case "EACCES":
            case "EPERM":
                return `Tool '${toolName}' failed: permission denied accessing the filesystem.`;
            case "ENOSPC":
                return `Tool '${toolName}' failed: no space left on disk.`;
            case "EMFILE":
                return `Tool '${toolName}' failed: too many open files.`;
            default:
                return `Tool '${toolName}' failed with a filesystem error (${err.code}).`;
        }
    }

    // HTTP-status-bearing errors from the search/LLM API clients (Tavily, OpenRouter)
    const status = err?.status ?? err?.statusCode;
    if (typeof status === "number") {
        if (status === 429) return `Tool '${toolName}' failed: rate limited, try again later.`;
        if (status === 401 || status === 403) return `Tool '${toolName}' failed: authentication error.`;
        if (status >= 500) return `Tool '${toolName}' failed: upstream service error (${status}).`;
        return `Tool '${toolName}' failed with HTTP status ${status}.`;
    }

    // Node's built-in fetch throws a TypeError for network-level failures (DNS, connection refused, etc.)
    if (error instanceof TypeError && "cause" in err) {
        return `Tool '${toolName}' failed: the network request could not be completed.`;
    }

    // A bare TypeError with no network `cause` is more likely an actual bug in the tool implementation
    if (error instanceof TypeError) {
        return `Tool '${toolName}' failed with TypeError.`;
    }
}