import {
    type ToolCallRequest
} from "langchain";

export function onRetry(error: unknown, request: ToolCallRequest): string | undefined {
    const toolName = request.toolCall.name;
    const err = error as Partial<NodeJS.ErrnoException> & { status?: number; statusCode?: number };

    // Node filesystem errors (readFile/writeFile/mkdir/appendFile) carry a `.code`
    if (err?.code) {
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