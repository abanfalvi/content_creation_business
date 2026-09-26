import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { dataPaths } from "../shared/paths.js";

// Local index of TUI sessions. The conversation itself lives in the orchestrator's
// checkpointer under the same thread_id; this file only keeps titles and timestamps.
export type Session = { id: string; title: string; createdAt: string; updatedAt: string };

const TITLE_MAX_LENGTH = 60;

function readAll(): Session[] {
    try {
        return JSON.parse(readFileSync(dataPaths.sessionsIndex(), "utf-8")) as Session[];
    } catch {
        return [];
    }
}

function writeAll(sessions: Session[]): void {
    const file = dataPaths.sessionsIndex();
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, JSON.stringify(sessions, null, 2));
}

export function listSessions(): Session[] {
    return readAll().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

// Creates the session on its first message (title = that message), otherwise bumps updatedAt.
export function touchSession(id: string, firstMessage: string): void {
    const sessions = readAll();
    const now = new Date().toISOString();
    const existing = sessions.find((s) => s.id === id);
    if (existing) {
        existing.updatedAt = now;
    } else {
        const title = firstMessage.replace(/\s+/g, " ").slice(0, TITLE_MAX_LENGTH);
        sessions.push({ id, title, createdAt: now, updatedAt: now });
    }
    writeAll(sessions);
}

export function removeSession(id: string): void {
    writeAll(readAll().filter((s) => s.id !== id));
}
