import { test } from "node:test";
import assert from "node:assert/strict";
import { onRetry } from "../src/shared/on_error.js";
import type { ToolCallRequest } from "langchain";

const tcRequest = {toolCall: {name: "exampleTool"}} as ToolCallRequest;

test("onRetry check correct ENOENT error response", () => {
    const errorObject = Object.assign(new Error("ENOENT: no such file"), { code: "ENOENT" })
    const result = onRetry(errorObject, tcRequest)
    assert.equal(result, `Tool 'exampleTool' failed: a required file was not found.`)
})

test("onRetry check correct EPERM error response", () => {
    const errorObject = Object.assign(new Error("EPERM: permission denied"), { code: "EPERM" })
    const result = onRetry(errorObject, tcRequest)
    assert.equal(result, `Tool 'exampleTool' failed: permission denied accessing the filesystem.`)
})

test("onRetry check correct ENOSPC error response", () => {
    const errorObject = Object.assign(new Error("ENOSPC: no more space on disk"), { code: "ENOSPC" })
    const result = onRetry(errorObject, tcRequest)
    assert.equal(result, `Tool 'exampleTool' failed: no space left on disk.`)
})

test("onRetry check correct EMFILE error response", () => {
    const errorObject = Object.assign(new Error("EMFILE: too many open files."), { code: "EMFILE" })
    const result = onRetry(errorObject, tcRequest)
    assert.equal(result, `Tool 'exampleTool' failed: too many open files.`)
})

test("onRetry check correct NEW error response", () => {
    const errorObject = Object.assign(new Error("NEW: something unexpected happened"), { code: "NEW" })
    const result = onRetry(errorObject, tcRequest)
    assert.equal(result, `Tool 'exampleTool' failed with a filesystem error (${errorObject.code}).`)
})

// HTTP-status errors
test("onRetry check 429 HTTP status error", () => {
    const errorObject = Object.assign(new Error("Too Many Requests"), { status: 429 })
    const result = onRetry(errorObject, tcRequest)
    assert.equal(result, `Tool 'exampleTool' failed: rate limited, try again later.`)
})

test("onRetry check 401 HTTP status error", () => {
    const errorObject = Object.assign(new Error("Forbidden"), { status: 401 })
    const result = onRetry(errorObject, tcRequest)
    assert.equal(result, `Tool 'exampleTool' failed: authentication error.`)
})

test("onRetry check 403 HTTP status error", () => {
    const errorObject = Object.assign(new Error("Forbidden"), { status: 403 })
    const result = onRetry(errorObject, tcRequest)
    assert.equal(result, `Tool 'exampleTool' failed: authentication error.`)
})

test("onRetry check 502 HTTP status error", () => {
    const errorObject = Object.assign(new Error("Error in upstream service"), { status: 502 })
    const result = onRetry(errorObject, tcRequest)
    assert.equal(result, `Tool 'exampleTool' failed: upstream service error (${errorObject.status}).`)
})

test("onRetry check 388 HTTP status error", () => {
    const errorObject = Object.assign(new Error("Unknown HTTP error"), { status: 388 })
    const result = onRetry(errorObject, tcRequest)
    assert.equal(result, `Tool 'exampleTool' failed with HTTP status ${errorObject.status}.`)
})

// Network level TypeError
test("onRetry check network level TypeError", () => {
    const errorObject = new TypeError("fetch failed", { cause: new Error("ECONNREFUSED") })
    const result = onRetry(errorObject, tcRequest)
    assert.equal(result, `Tool 'exampleTool' failed: the network request could not be completed.`)
})

// Bare TypeError
test("onRetry check bare TypeError", () => {
    const errorObject = new TypeError("Cannot read properties of undefined (reading 'x')")
    const result = onRetry(errorObject, tcRequest)
    assert.equal(result, `Tool 'exampleTool' failed with TypeError.`)
})

// No match
test("onRetry check what happens in case of no match", () => {
    const errorObject = new Error("something unrelated")
    const result = onRetry(errorObject, tcRequest)
    assert.equal(result, undefined)
})