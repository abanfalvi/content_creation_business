import { test } from "node:test";
import assert from "node:assert/strict";
import { tool, type DynamicStructuredTool } from "@langchain/core/tools";
import { z } from "zod";
import { BEEHIIV_WRITE_TOOLS, guardWriteTools, sideEffectLog } from "./eval_guard.js";

let realCalls = 0;
const makeTool = (name: string) =>
    tool(async () => {
        realCalls += 1;
        return "real result";
    }, { name, description: name, schema: z.object({ title: z.string() }) }) as unknown as DynamicStructuredTool;

test("outside eval mode, tools are returned untouched", async () => {
    delete process.env.EVAL_MODE;
    const tools = [makeTool("save_post")];
    assert.equal(guardWriteTools("beehiiv", tools, BEEHIIV_WRITE_TOOLS)[0], tools[0]);
});

test("in eval mode, write tools are recorded instead of executed", async () => {
    process.env.EVAL_MODE = "1";
    realCalls = 0;
    const before = sideEffectLog.length;
    const [savePost] = guardWriteTools("beehiiv", [makeTool("save_post")], BEEHIIV_WRITE_TOOLS);

    const result = await savePost!.invoke({ title: "Eval draft" });

    assert.equal(realCalls, 0);
    assert.match(String(result), /"success":true/);
    assert.deepEqual(sideEffectLog.slice(before).map(({ server, tool, args }) => ({ server, tool, args })), [
        { server: "beehiiv", tool: "save_post", args: { title: "Eval draft" } },
    ]);
    delete process.env.EVAL_MODE;
});

test("in eval mode, read tools still execute for real", async () => {
    process.env.EVAL_MODE = "1";
    realCalls = 0;
    const original = makeTool("get_post");
    const [getPost] = guardWriteTools("beehiiv", [original], BEEHIIV_WRITE_TOOLS);

    assert.equal(getPost, original);
    assert.equal(await getPost!.invoke({ title: "x" }), "real result");
    assert.equal(realCalls, 1);
    delete process.env.EVAL_MODE;
});
