import { useCallback, useEffect, useRef, useState } from "react";
import { Box, Text, Static, useApp, useInput } from "ink";
import { HumanMessage, type BaseMessage } from "@langchain/core/messages";
import { orchestratorAgent } from "../orchestrator/orchestrator.js";
import { opikHandler, MODELS } from "../models.js";
import { messagesToEntries, type ChatEntryDraft } from "./message_format.js";
import { Home } from "./Home.js";

type ChatEntry = ChatEntryDraft & { id: string };

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const SPINNER_INTERVAL_MS = 80;
const RECURSION_LIMIT = 50;
const EXIT_COMMANDS = new Set(["/exit", "/quit"]);

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
    return (
        <Box flexDirection="column" marginBottom={1}>
            <Text color={color} bold>{label}</Text>
            <Text dimColor={dim}>{entry.text}</Text>
        </Box>
    );
}

function TextInputLine({ onSubmit, disabled }: { onSubmit: (value: string) => void; disabled: boolean }) {
    const [value, setValue] = useState("");

    useInput((input, key) => {
        if (disabled) return;
        if (key.return) {
            const trimmed = value.trim();
            if (trimmed.length > 0) {
                onSubmit(trimmed);
                setValue("");
            }
            return;
        }
        if (key.backspace || key.delete) {
            setValue((v) => v.slice(0, -1));
            return;
        }
        if (key.ctrl || key.meta || key.upArrow || key.downArrow || key.leftArrow || key.rightArrow || key.tab) return;
        if (input) setValue((v) => v + input);
    });

    return (
        <Box borderStyle="round" borderColor={disabled ? "gray" : "green"} paddingX={1}>
            <Text color="green">{"> "}</Text>
            <Text wrap="truncate-end">{value}</Text>
            {!disabled && <Text color="gray">▌</Text>}
        </Box>
    );
}

export function App({ threadId, version, cwd }: { threadId: string; version: string; cwd: string }) {
    const { exit } = useApp();
    const [started, setStarted] = useState(false);
    const [entries, setEntries] = useState<ChatEntry[]>([]);
    const [isProcessing, setIsProcessing] = useState(false);
    const [statusText, setStatusText] = useState("");
    const seenCountRef = useRef(0);
    const entryIdRef = useRef(0);

    const pushEntry = useCallback((entry: ChatEntryDraft) => {
        entryIdRef.current += 1;
        setEntries((prev) => [...prev, { ...entry, id: `e${entryIdRef.current}` }]);
    }, []);

    const quit = useCallback(() => {
        opikHandler.flushAsync().finally(() => exit());
    }, [exit]);

    const handleSubmit = useCallback(async (text: string) => {
        if (EXIT_COMMANDS.has(text)) {
            quit();
            return;
        }

        setStarted(true);
        pushEntry({ role: "user", text });
        seenCountRef.current += 1;
        setIsProcessing(true);
        setStatusText("thinking…");

        try {
            const stream = await orchestratorAgent.stream(
                { messages: [new HumanMessage(text)] },
                {
                    configurable: { thread_id: threadId },
                    streamMode: "values",
                    recursionLimit: RECURSION_LIMIT,
                    callbacks: [opikHandler],
                },
            );

            for await (const state of stream) {
                const messages = (state.messages ?? []) as BaseMessage[];
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
    }, [threadId, pushEntry, quit]);

    useInput((input, key) => {
        if (key.ctrl && input === "c") quit();
    });

    return (
        <Box flexDirection="column">
            {started && (
                <Static items={entries}>
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
                <TextInputLine onSubmit={handleSubmit} disabled={isProcessing} />

            </Box>
        </Box>
    );
}
