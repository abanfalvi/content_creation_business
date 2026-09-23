import { test } from "node:test";
import assert from "node:assert/strict";
import { messagesToEntries, type ChatEntryDraft } from "../src/tui/message_format.js";
import { AIMessage, HumanMessage, ToolMessage } from "langchain";

test("Check messagesToEntries if it returns proper user-assistant message pair", () => {
    const messages = [
        new HumanMessage("What's the weather?"),
        new AIMessage({ content: "Checking the weather, using the tool...", tool_calls: [{ name: "get_weather", args: { city: "Paris" } }] }),
        new ToolMessage({ content: "22°C, sunny", tool_call_id: "call_1", name: "get_weather" }),
    ]
    const resultFormat: ChatEntryDraft[] = [
        {role: "user", text: "What's the weather?"},
        {role: "status", text: `→ calling get_weather({"city":"Paris"})`},
        {role: "assistant", text: "Checking the weather, using the tool..."},
        {role: "tool", text: "get_weather → 22°C, sunny"}
    ]
    const result = messagesToEntries(messages)
    assert.deepEqual(result, resultFormat)
})