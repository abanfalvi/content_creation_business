// Capabilities: retrieve the relevant context
import { tool, type ToolRuntime } from "@langchain/core/tools";
import { HumanMessage, ToolMessage } from "@langchain/core/messages";
import { Command } from "@langchain/langgraph";
import matter from "gray-matter";
import { z } from "zod";
import { glob, mkdir, rename, readdir, rmdir, access } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { dataPaths } from "../shared/paths.js";

const MEMORIES_ROOT = path.resolve(dataPaths.memories());

// Map a virtual path ("/audience/x.md") to a real path, refusing anything outside the memories folder
function resolveMemoryPath(virtualPath: string): string {
    const resolved = path.resolve(MEMORIES_ROOT, "." + path.posix.normalize("/" + virtualPath));
    if (resolved !== MEMORIES_ROOT && !resolved.startsWith(MEMORIES_ROOT + path.sep)) {
        throw new Error(`Path is outside the memories folder: ${virtualPath}`);
    }
    return resolved;
}


const contextSearch = tool(
    async ({filePath}) => {
        const relFilePath = resolveMemoryPath(filePath);
        const relFiles: Record<string, Record<string, unknown>> = {};
        for await (const p of glob("**/*.md", {cwd: relFilePath})) {
            const { data } = matter.read(path.join(relFilePath, p));
            relFiles[p.split(path.sep).join("/")] = data;
        }

        return relFiles;
    }, {
        name: "context_search",
        description: "Use this to retrieve the summary descriptions of the files stored in memories, to see if there is any relevant stored already",
        schema: z.object({
            filePath: z.string()
        })
    }
);

const moveItem = tool(
    async ({fromPath, toPath}) => {
        const from = resolveMemoryPath(fromPath);
        const to = resolveMemoryPath(toPath);
        if (from === MEMORIES_ROOT || to === MEMORIES_ROOT) {
            return "Error: cannot move the memories root itself";
        }
        if (to.startsWith(from + path.sep)) {
            return `Error: cannot move ${fromPath} into itself`;
        }
        try {
            await access(from);
        } catch {
            return `Error: ${fromPath} does not exist`;
        }
        try {
            await access(to);
            return `Error: ${toPath} already exists — choose another name or merge by hand`;
        } catch {}

        await mkdir(path.dirname(to), {recursive: true});
        await rename(from, to);

        // Remove source folders left empty by the move, up to (not including) the root
        let dir = path.dirname(from);
        while (dir !== MEMORIES_ROOT && (await readdir(dir)).length === 0) {
            await rmdir(dir);
            dir = path.dirname(dir);
        }

        return `Moved ${fromPath} -> ${toPath}`;
    }, {
        name: "move_item",
        description: "Move or rename a memory file or folder inside the memories folder. Missing destination folders are created, emptied source folders are removed, and existing destinations are never overwritten.",
        schema: z.object({
            fromPath: z.string().describe("Current path, e.g. /audience/length.md or /audience"),
            toPath: z.string().describe("New path, e.g. /audience/engagement/length.md"),
        })
    }
);

export const memoryManageAgentTools = [contextSearch, moveItem];