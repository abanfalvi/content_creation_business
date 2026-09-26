import { test } from "node:test";
import assert from "node:assert/strict";
import type { ToolCallRequest } from "langchain";
import { onRetry } from "./on_error.js";

const request = { toolCall: { name: "get_post_content", args: {}, id: "call_1" } } as unknown as ToolCallRequest;

function toolException(message: string): Error {
    const error = new Error(message);
    error.name = "ToolException";
    return error;
}

test("MCP server errors are passed to the model with the server's text", () => {
    const result = onRetry(toolException("MCP tool 'get_post_content' on server 'beehiiv' returned an error: Resource not found"), request);
    assert.match(result!, /rejected by its server: Resource not found/);
});

test("MCP JSON-RPC errors are classified by code", () => {
    assert.match(onRetry(toolException("Error calling tool get_post_content: McpError: MCP error -32602: post_id is required"), request)!, /invalid arguments.*post_id is required/s);
    assert.match(onRetry(toolException("Error calling tool get_post_content: McpError: MCP error -32001: Request timed out"), request)!, /timed out/);
    assert.match(onRetry(toolException("Error calling tool get_post_content: McpError: MCP error -32000: Connection closed"), request)!, /connection to its server closed/);
});

test("MCP auth and HTTP failures tell the model not to loop", () => {
    assert.match(onRetry(toolException("Error calling tool get_post_content: UnauthorizedError: Unauthorized"), request)!, /re-authorized/);
    assert.match(onRetry(toolException("Error calling tool get_post_content: Error: Streamable HTTP error: Error POSTing to endpoint (HTTP 503): down"), request)!, /internal error \(503\)/);
});

test("long MCP error text is clipped", () => {
    const result = onRetry(toolException(`MCP tool 'x' on server 'y' returned an error: ${"a".repeat(5000)}`), request)!;
    assert.ok(result.length < 1700);
});

test("filesystem errors still map by code", () => {
    const error = Object.assign(new Error("nope"), { code: "ENOENT" });
    assert.match(onRetry(error, request)!, /file was not found/);
});

test("unclassified errors still propagate", () => {
    assert.equal(onRetry(new Error("boom"), request), undefined);
});
