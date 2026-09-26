import { randomUUID } from "node:crypto";
import { useCallback, useEffect, useRef, useState } from "react";
import { Box, Text, Static, useApp, useInput, useStdout } from "ink";
import { HumanMessage, type BaseMessage } from "@langchain/core/messages";
import { orchestratorAgent } from "../orchestrator/orchestrator.js";
import { checkpointer } from "../orchestrator/checkpointer.js";
import { opikHandler, MODELS } from "../models.js";
import { messagesToEntries, progressEventToEntry, type ChatEntryDraft } from "./message_format.js";
import type { ProgressEvent } from "../shared/progress_update.js";
import { listSessions, removeSession, touchSession, type Session } from "./sessions.js";
import { Home } from "./Home.js";

type ChatEntry = ChatEntryDraft & { id: string };
type Command = { name: string; description: string };

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const SPINNER_INTERVAL_MS = 80;
const RECURSION_LIMIT = 50;
const PICKER_VISIBLE_ROWS = 8;
const CLEAR_SCREEN = "\x1b[2J\x1b[3J\x1b[H";
const COMMANDS: Command[] = [
    { name: "/sessions", description: "switch to a previous session" },
    { name: "/new", description: "start a new session" },
    { name: "/exit", description: "quit" },
];

const newThreadId = () => randomUUID().slice(0, 8);

function Spinner() {
    const [frame, setFrame] = useState(0);
    useEffect(() => {
        const timer = setInterval(() => setFrame((f) => (f + 1) % SPINNER_FRAMES.length), SPINNER_INTERVAL_MS);
        return () => clearInterval(timer);
    }, []);
    return <Text color="cyan">{SPINNER_FRAMES[frame]}</Text>;
}

function roleStyle(role: ChatEntry["role"]): { label: string; color: string; dim: boolean } {
    switch (role) {
        case "user": return { label: "you", color: "green", dim: false };
        case "assistant": return { label: "orchestrator", color: "cyan", dim: false };
        case "tool": return { label: "tool", color: "gray", dim: true };
        case "status": return { label: "…", color: "yellow", dim: true };
        case "error": return { label: "error", color: "red", dim: false };
    }
}

function ChatLine({ entry }: { entry: ChatEntry }) {
    const { label, color, dim } = roleStyle(entry.role);
    const depth = entry.depth ?? 0;
    if (depth > 0) {
        return (
            <Box marginLeft={(depth - 1) * 2}>
                <Text dimColor>{"└ "}</Text>
                <Text color="magenta">{entry.agent} </Text>
                <Text dimColor={dim}>{entry.text}</Text>
            </Box>
        );
    }
    return (
        <Box flexDirection="column" marginBottom={1}>
            <Text color={color} bold>{label}</Text>
            <Text dimColor={dim}>{entry.text}</Text>
        </Box>
    );
}

function InputBox({ value, disabled }: { value: string; disabled: boolean }) {
    return (
        <Box borderStyle="round" borderColor={disabled ? "gray" : "green"} paddingX={1}>
            <Text color="green">{"> "}</Text>
            <Text wrap="truncate-end">{value}</Text>
            {!disabled && <Text color="gray">▌</Text>}
        </Box>
    );
}

function CommandMenu({ commands, selected }: { commands: Command[]; selected: number }) {
    return (
        <Box flexDirection="column" paddingX={1}>
            {commands.map((command, i) => (
                <Text key={command.name} {...(i === selected && { color: "cyan" })}>
                    {i === selected ? "❯ " : "  "}
                    <Text bold>{command.name.padEnd(12)}</Text>
                    <Text dimColor>{command.description}</Text>
                </Text>
            ))}
        </Box>
    );
}

function SessionPicker({ sessions, selected, currentId, pendingDeleteId }: {
    sessions: Session[]; selected: number; currentId: string; pendingDeleteId: string | null;
}) {
    if (sessions.length === 0) {
        return <Box paddingX={1}><Text dimColor>No saved sessions yet · esc to close</Text></Box>;
    }
    const offset = Math.max(0, Math.min(selected - PICKER_VISIBLE_ROWS + 1, sessions.length - PICKER_VISIBLE_ROWS));
    const visible = sessions.slice(offset, offset + PICKER_VISIBLE_ROWS);
    return (
        <Box flexDirection="column" paddingX={1}>
            {visible.map((session, i) => {
                const isSelected = offset + i === selected;
                return (
                    <Text key={session.id} {...(isSelected && { color: "cyan" })}>
                        {isSelected ? "❯ " : "  "}
                        {session.title}
                        <Text dimColor> · {new Date(session.updatedAt).toLocaleString()} · {session.id}</Text>
                        {session.id === currentId && <Text color="green"> (current)</Text>}
                        {session.id === pendingDeleteId && <Text color="red"> press d again to delete</Text>}
                    </Text>
                );
            })}
            <Text dimColor>↑↓ select · enter open · dd delete · esc close</Text>
        </Box>
    );
}

export function App({ threadId: initialThreadId, version, cwd }: { threadId: string; version: string; cwd: string }) {
    const { exit } = useApp();
    const { stdout } = useStdout();
    const [threadId, setThreadId] = useState(initialThreadId);
    const [started, setStarted] = useState(false);
    const [entries, setEntries] = useState<ChatEntry[]>([]);
    const [staticKey, setStaticKey] = useState(0);
    const [isProcessing, setIsProcessing] = useState(false);
    const [statusText, setStatusText] = useState("");
    const [input, setInput] = useState("");
    const [menuIndex, setMenuIndex] = useState(0);
    const [picker, setPicker] = useState<{ sessions: Session[]; selected: number } | null>(null);
    const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
    const seenCountRef = useRef(0);
    const entryIdRef = useRef(0);

    const matchingCommands = input.startsWith("/") && !input.includes(" ")
        ? COMMANDS.filter((c) => c.name.startsWith(input))
        : [];
    const menuOpen = !picker && matchingCommands.length > 0;

    const pushEntry = useCallback((entry: ChatEntryDraft) => {
        entryIdRef.current += 1;
        setEntries((prev) => [...prev, { ...entry, id: `e${entryIdRef.current}` }]);
    }, []);

    const quit = useCallback(() => {
        opikHandler.flushAsync().finally(() => exit());
    }, [exit]);

    // <Static> never erases what it already printed, so switching sessions clears the
    // terminal and remounts it with the new session's history.
    const resetView = useCallback((drafts: ChatEntryDraft[], messageCount: number) => {
        stdout.write(CLEAR_SCREEN);
        setEntries(drafts.map((d, i) => ({ ...d, id: `e${entryIdRef.current + i + 1}` })));
        entryIdRef.current += drafts.length;
        setStaticKey((k) => k + 1);
        seenCountRef.current = messageCount;
        setStarted(drafts.length > 0);
    }, [stdout]);

    const startNewSession = useCallback(() => {
        setThreadId(newThreadId());
        resetView([], 0);
    }, [resetView]);

    const openSession = useCallback(async (id: string) => {
        const snapshot = await orchestratorAgent.graph.getState({ configurable: { thread_id: id } });
        const messages = ((snapshot.values as { messages?: BaseMessage[] }).messages ?? []);
        setThreadId(id);
        resetView(messagesToEntries(messages), messages.length);
    }, [resetView]);

    const deleteSession = useCallback(async (id: string) => {
        removeSession(id);
        await checkpointer.deleteThread(id);
        const sessions = listSessions();
        setPicker((p) => p && { sessions, selected: Math.min(p.selected, Math.max(0, sessions.length - 1)) });
        if (id === threadId) startNewSession();
    }, [threadId, startNewSession]);

    const runCommand = useCallback((name: string) => {
        switch (name) {
            case "/exit":
            case "/quit":
                quit();
                return true;
            case "/new":
                startNewSession();
                return true;
            case "/sessions":
                setPicker({ sessions: listSessions(), selected: 0 });
                setPendingDeleteId(null);
                return true;
        }
        return false;
    }, [quit, startNewSession]);

    const handleSubmit = useCallback(async (text: string) => {
        if (runCommand(text)) return;

        setStarted(true);
        pushEntry({ role: "user", text });
        touchSession(threadId, text);
        seenCountRef.current += 1;
        setIsProcessing(true);
        setStatusText("thinking…");

        try {
            const stream = await orchestratorAgent.stream(
                { messages: [new HumanMessage(text)] },
                {
                    configurable: { thread_id: threadId },
                    streamMode: ["values", "custom"],
                    recursionLimit: RECURSION_LIMIT,
                    callbacks: [opikHandler],
                },
            );

            for await (const [mode, data] of stream) {
                if (mode === "custom") {
                    const event = data as ProgressEvent;
                    pushEntry(progressEventToEntry(event));
                    if (event.type === "agent_start") setStatusText(`🔧 ${event.agent} is working…`);
                    continue;
                }
                const messages = (data.messages ?? []) as BaseMessage[];
                if (messages.length <= seenCountRef.current) continue;
                const newMessages = messages.slice(seenCountRef.current);
                seenCountRef.current = messages.length;

                for (const entry of messagesToEntries(newMessages)) {
                    pushEntry(entry);
                    if (entry.role === "status") setStatusText(entry.text);
                }
            }
        } catch (error) {
            pushEntry({ role: "error", text: error instanceof Error ? error.message : String(error) });
        } finally {
            setIsProcessing(false);
            setStatusText("");
        }
    }, [threadId, pushEntry, runCommand]);

    useInput((char, key) => {
        if (key.ctrl && char === "c") {
            quit();
            return;
        }
        if (isProcessing) return;

        if (picker) {
            const current = picker.sessions[picker.selected];
            if (char === "d" && current) {
                if (pendingDeleteId === current.id) {
                    setPendingDeleteId(null);
                    void deleteSession(current.id);
                } else {
                    setPendingDeleteId(current.id);
                }
                return;
            }
            setPendingDeleteId(null);
            if (key.escape) setPicker(null);
            else if (key.upArrow) setPicker({ ...picker, selected: Math.max(0, picker.selected - 1) });
            else if (key.downArrow) setPicker({ ...picker, selected: Math.min(picker.sessions.length - 1, picker.selected + 1) });
            else if (key.return && current) {
                setPicker(null);
                void openSession(current.id).catch((error: unknown) =>
                    pushEntry({ role: "error", text: error instanceof Error ? error.message : String(error) }));
            }
            return;
        }

        if (menuOpen) {
            const selected = Math.min(menuIndex, matchingCommands.length - 1);
            if (key.upArrow) { setMenuIndex(Math.max(0, selected - 1)); return; }
            if (key.downArrow) { setMenuIndex(Math.min(matchingCommands.length - 1, selected + 1)); return; }
            if (key.escape) { setInput(""); return; }
            if (key.tab || key.return) {
                setInput("");
                setMenuIndex(0);
                runCommand(matchingCommands[selected]!.name);
                return;
            }
        }

        if (key.return) {
            const trimmed = input.trim();
            if (trimmed.length > 0) {
                setInput("");
                void handleSubmit(trimmed);
            }
            return;
        }
        if (key.backspace || key.delete) {
            setInput((v) => v.slice(0, -1));
            setMenuIndex(0);
            return;
        }
        if (key.ctrl || key.meta || key.escape || key.upArrow || key.downArrow || key.leftArrow || key.rightArrow || key.tab) return;
        if (char) {
            setInput((v) => v + char);
            setMenuIndex(0);
        }
    });

    return (
        <Box flexDirection="column">
            {started && (
                <Static key={staticKey} items={entries}>
                    {(entry) => <ChatLine key={entry.id} entry={entry} />}
                </Static>
            )}
            <Box marginTop={started ? 1 : 0} flexDirection="column">
                {!started && (
                    <Home threadId={threadId} model={MODELS.MAIN_ORCHESTRATOR_MODEL} version={version} cwd={cwd} />
                )}
                {isProcessing && (
                    <Box gap={1}>
                        <Spinner />
                        <Text color="yellow">{statusText || "working…"}</Text>
                    </Box>
                )}
                {picker && (
                    <SessionPicker sessions={picker.sessions} selected={picker.selected} currentId={threadId} pendingDeleteId={pendingDeleteId} />
                )}
                {menuOpen && <CommandMenu commands={matchingCommands} selected={Math.min(menuIndex, matchingCommands.length - 1)} />}
                <InputBox value={input} disabled={isProcessing || picker !== null} />
            </Box>
        </Box>
    );
}
