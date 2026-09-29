import chalk from "chalk";
import { Marked } from "marked";
import { markedTerminal } from "marked-terminal";
import wrapAnsi from "wrap-ansi";
import type { ChatEntryDraft } from "./message_format.js";

const markdown = new Marked(markedTerminal({ reflowText: false, tab: 2 }) as Parameters<Marked["use"]>[0]);
// marked-terminal emits list-item text raw, leaving **bold**/`code` unrendered, so
// parse the inline tokens ourselves.
markdown.use({
    renderer: {
        text(token) {
            return "tokens" in token && token.tokens ? this.parser.parseInline(token.tokens) : false;
        },
    },
});

function renderMarkdown(text: string): string {
    try {
        return (markdown.parse(text) as string).replace(/\n+$/, "");
    } catch {
        return text;
    }
}

function wrap(text: string, width: number): string[] {
    return wrapAnsi(text, Math.max(1, width), { hard: true, trim: false }).split("\n");
}

const ROLE_LABELS: Record<ChatEntryDraft["role"], string> = {
    user: chalk.green.bold("you"),
    assistant: chalk.cyan.bold("orchestrator"),
    tool: chalk.gray.bold("tool"),
    status: chalk.yellow.bold("…"),
    error: chalk.red.bold("error"),
};

// Entries are immutable, so cache per entry object: the styled body (width-independent,
// includes the markdown parse) and the lines for the last width it was wrapped to.
// Resizing then only re-wraps, and other re-renders reuse the lines as-is.
const cache = new WeakMap<ChatEntryDraft, { body: string; width?: number; lines?: string[] }>();

function styledBody(entry: ChatEntryDraft): string {
    const depth = entry.depth ?? 0;
    if (depth > 0) {
        const indent = " ".repeat((depth - 1) * 2);
        const dim = entry.role === "tool" || entry.role === "status";
        return `${indent}${chalk.dim("└ ")}${chalk.magenta(entry.agent ?? "")} ${dim ? chalk.dim(entry.text) : entry.text}`;
    }
    return entry.role === "assistant"
        ? renderMarkdown(entry.text)
        : entry.role === "tool" || entry.role === "status" ? chalk.dim(entry.text) : entry.text;
}

// Flattens one chat entry into terminal lines already wrapped to `width`, so the
// viewport can scroll by line.
export function entryToLines(entry: ChatEntryDraft, width: number): string[] {
    let cached = cache.get(entry);
    if (!cached) {
        cached = { body: styledBody(entry) };
        cache.set(entry, cached);
    }
    if (cached.width !== width || !cached.lines) {
        const wrapped = wrap(cached.body, width);
        cached.lines = (entry.depth ?? 0) > 0 ? wrapped : [ROLE_LABELS[entry.role], ...wrapped, ""];
        cached.width = width;
    }
    return cached.lines;
}
