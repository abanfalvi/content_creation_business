import { randomUUID } from "node:crypto";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Box, Text, measureElement, useApp, useInput, useStdout, type DOMElement } from "ink";
import { appendFileSync } from "node:fs";
import { AIMessage, HumanMessage, ToolMessage, type BaseMessage } from "@langchain/core/messages";
import { orchestratorAgent } from "../orchestrator/orchestrator.js";
import { checkpointer } from "../orchestrator/checkpointer.js";
import { opikHandler, MODELS } from "../models.js";
import { isAgentStep, messagesToEntries, progressEventToEntry, type ChatEntryDraft } from "./message_format.js";
import type { ProgressEvent } from "../shared/progress_update.js";
import { listSessions, removeSession, touchSession, type Session } from "./sessions.js";
import { Home } from "./Home.js";
import { entryToLines } from "./chat_render.js";
import { getTotalCost, onCostChange } from "../shared/cost_tracker.js";
import { countContextTokens, fetchContextWindow } from "./context_usage.js";

type ChatEntry = ChatEntryDraft & { id: string };
const RESIZE_DEBOUNCE_MS = 60;
type Command = { name: string; description: string };

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const SPINNER_INTERVAL_MS = 80;
const RECURSION_LIMIT = 500;
const PICKER_VISIBLE_ROWS = 8;
// Set NL_TUI_DEBUG_INPUT=<file> to log every key/mouse event the TUI receives.
const DEBUG_INPUT_FILE = process.env.NL_TUI_DEBUG_INPUT;
const SCROLLBAR_WIDTH = 2;
const WHEEL_STEP = 3;
const MOUSE_ON = "\x1b[?1002h\x1b[?1006h";
const MOUSE_OFF = "\x1b[?1002l\x1b[?1006l";
const MOUSE_DEFAULT = process.env.NL_TUI_MOUSE ? process.env.NL_TUI_MOUSE === "1" : process.platform !== "win32";
const TERMINAL_REPLY = /^\x1b?\[\?[\d;]*[a-zA-Z]$/;
const MOUSE_EVENT =/\[<(\d+);(\d+);(\d+)([Mm])/g;
const COMMANDS: Command[] = [
    { name: "/sessions", description: "switch to a previous session" },
    { name: "/mouse", description: "toggle mouse mode (scrollbar dragging vs. text selection)" },
    { name: "/new", description: "start a new session" },
    { name: "/queue", description: "queue another message for the agent" },
    { name: "/steer", description: "steer the agent into another direction" },
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

// `offset` is lines scrolled up from the bottom.
function Scrollbar({ height, total, offset }: { height: number; total: number; offset: number }) {
    if (height <= 0) return null;
    const maxScroll = Math.max(0, total - height);
    const thumb = maxScroll === 0 ? height : Math.max(1, Math.round((height * height) / total));
    const thumbTop = maxScroll === 0 ? 0 : Math.round(((maxScroll - offset) / maxScroll) * (height - thumb));
    return (
        <Box flexDirection="column" width={SCROLLBAR_WIDTH} flexShrink={0} paddingLeft={1}>
            {Array.from({ length: height }, (_, i) => {
                const inThumb = i >= thumbTop && i < thumbTop + thumb;
                return <Text key={i} color={inThumb ? "cyan" : "gray"}>{inThumb ? "█" : "│"}</Text>;
            })}
        </Box>
    );
}

function StepsToggle({ shown }: { shown: boolean }) {
    return (
        <Box paddingX={1}>
            <Text color={shown ? "cyan" : "gray"}>{shown ? "▾" : "▸"} agent steps: {shown ? "shown" : "hidden"}</Text>
            <Text dimColor> · click or ctrl+o to toggle</Text>
        </Box>
    );
}

const BAR_WIDTH = 20;
const formatTokens = (n: number) => {
    if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(2)}M`;
    return n >= 1000 ? `${(n / 1000).toFixed(n >= 100_000 ? 0 : 1)}k` : String(n);
};

const formatCost = (usd: number) => `$${usd.toFixed(usd < 1 ? 4 : 2)}`;

function ContextBar({ used, max, cost }: { used: number; max: number; cost: number }) {
    const fraction = Math.min(1, used / max);
    const filled = Math.round(fraction * BAR_WIDTH);
    const color = fraction >= 0.9 ? "red" : fraction >= 0.7 ? "yellow" : "green";
    return (
        <Box paddingX={1} gap={1}>
            <Text dimColor>context {formatTokens(used)}/{formatTokens(max)} →</Text>
            <Text color={color}>{"█".repeat(filled)}<Text color="gray">{"░".repeat(BAR_WIDTH - filled)}</Text></Text>
            <Text color={color}>{(fraction * 100).toFixed(1)}%</Text>
            <Text dimColor>· spent {formatCost(cost)}</Text>
        </Box>
    );
}

type Editor = { text: string; cursor: number };

const lineStart = (text: string, pos: number) => text.lastIndexOf("\n", pos - 1) + 1;
const lineEnd = (text: string, pos: number) => {
    const end = text.indexOf("\n", pos);
    return end === -1 ? text.length : end;
};
const wordLeft = (text: string, pos: number) => {
    let i = pos;
    while (i > 0 && /\s/.test(text[i - 1]!)) i--;
    while (i > 0 && !/\s/.test(text[i - 1]!)) i--;
    return i;
};
const wordRight = (text: string, pos: number) => {
    let i = pos;
    while (i < text.length && /\s/.test(text[i]!)) i++;
    while (i < text.length && !/\s/.test(text[i]!)) i++;
    return i;
};

function InputBox({ editor, disabled }: { editor: Editor; disabled: boolean }) {
    const { text, cursor } = editor;
    const atCursor = text[cursor];
    // The cursor is drawn as an inverted cell over the character it sits on (a space
    // at the end of the text or before a line break).
    const cursorCell = atCursor === undefined || atCursor === "\n" ? " " : atCursor;
    const after = text.slice(atCursor === undefined || atCursor === "\n" ? cursor : cursor + 1);
    return (
        <Box borderStyle="round" borderColor={disabled ? "gray" : "green"} paddingX={1}>
            <Text color="green">{"> "}</Text>
            <Box flexGrow={1} flexShrink={1}>
                <Text wrap="wrap">
                    {text.slice(0, cursor)}
                    {disabled ? cursorCell.trim() : <Text inverse>{cursorCell}</Text>}
                    {after}
                </Text>
            </Box>
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
    const [entries, setEntries] = useState<ChatEntry[]>([]);
    const [scrollOffset, setScrollOffset] = useState(0);
    const [size, setSize] = useState({ columns: stdout.columns || 80, rows: stdout.rows || 24 });
    // Initial guesses until the first layout is measured.
    const [viewHeight, setViewHeight] = useState(Math.max(1, size.rows - 4));
    const [homeHeight, setHomeHeight] = useState(0);
    const [mouseEnabled, setMouseEnabled] = useState(MOUSE_DEFAULT);
    const [showSteps, setShowSteps] = useState(true);
    const [inputHeight, setInputHeight] = useState(3);
    const inputRef = useRef<DOMElement>(null);
    const chatRef = useRef<DOMElement>(null);
    const homeRef = useRef<DOMElement>(null);
    const [isProcessing, setIsProcessing] = useState(false);
    const [statusText, setStatusText] = useState("");
    const [editor, setEditor] = useState<Editor>({ text: "", cursor: 0 });
    const input = editor.text;
    const setInput = (text: string) => setEditor({ text, cursor: text.length });
    // Functional updates so bursts of keys (fast typing, key repeat) all apply.
    const insertText = (s: string) =>
        setEditor(({ text, cursor }) => ({ text: text.slice(0, cursor) + s + text.slice(cursor), cursor: cursor + s.length }));
    const moveCursor = (to: (e: Editor) => number) =>
        setEditor((e) => ({ ...e, cursor: Math.max(0, Math.min(e.text.length, to(e))) }));
    const [menuIndex, setMenuIndex] = useState(0);
    const [picker, setPicker] = useState<{ sessions: Session[]; selected: number } | null>(null);
    const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
    // Steering messages typed while a run is going. A ref, not state: the stream loop in
    // handleSubmit is a long-lived closure that has to see messages typed after it started.
    const steerRef = useRef<string[]>([]);
    const seenCountRef = useRef(0);
    const entryIdRef = useRef(0);
    const abortRef = useRef<AbortController | null>(null);
    const [queue, setQueue] = useState<string[]>([]);
    const [contextTokens, setContextTokens] = useState(0);
    const [contextWindow, setContextWindow] = useState(200_000);
    const [totalCost, setTotalCost] = useState(getTotalCost());

    useEffect(() => onCostChange(setTotalCost), []);

    useEffect(() => {
        void fetchContextWindow(MODELS.MAIN_ORCHESTRATOR_MODEL).then(setContextWindow);
        // Resumed sessions start with their existing context.
        void orchestratorAgent.graph.getState({ configurable: { thread_id: initialThreadId } })
            .then((s) => setContextTokens(countContextTokens((s.values as { messages?: BaseMessage[] }).messages ?? [])))
            .catch(() => {});
    }, [initialThreadId]);

    useEffect(() => {
        // Dragging a window edge fires a burst of resize events; only apply the last one.
        let timer: ReturnType<typeof setTimeout> | undefined;
        const onResize = () => {
            clearTimeout(timer);
            timer = setTimeout(() => setSize({ columns: stdout.columns || 80, rows: stdout.rows || 24 }), RESIZE_DEBOUNCE_MS);
        };
        stdout.on("resize", onResize);
        return () => { clearTimeout(timer); stdout.off("resize", onResize); };
    }, [stdout]);

    // The chat area's height depends on how tall the input/menus below it are, and the
    // Home banner's height on the terminal width, so measure both after every render.
    useEffect(() => {
        if (chatRef.current) {
            const { height } = measureElement(chatRef.current);
            if (height > 0 && height !== viewHeight) setViewHeight(height);
        }
        if (inputRef.current) {
            const { height } = measureElement(inputRef.current);
            if (height > 0 && height !== inputHeight) setInputHeight(height);
        }
        if (homeRef.current) {
            const { height } = measureElement(homeRef.current);
            if (height > 0 && height !== homeHeight) setHomeHeight(height);
        }
    });

    // Mouse reporting (button + drag, SGR encoding) lets the scrollbar be clicked/dragged.
    // Off by default on Windows: Node's console input there drops mouse events, and while
    // it's on the terminal stops translating wheel/touchpad scrolling into ↑/↓ — so it
    // would break scrolling instead of adding to it. Toggle with /mouse.
    useEffect(() => {
        if (!mouseEnabled) return;
        stdout.write(MOUSE_ON);
        return () => { stdout.write(MOUSE_OFF); };
    }, [stdout, mouseEnabled]);

    const chatLines = useMemo(
        () => entries
            .filter((entry) => showSteps || !isAgentStep(entry))
            .flatMap((entry) => entryToLines(entry, size.columns - SCROLLBAR_WIDTH)),
        [entries, size.columns, showSteps],
    );
    // The scrollable content is the Home banner (homeHeight rows, rendered as a real
    // component) followed by the chat lines. `offset` counts rows up from the bottom, so
    // new messages keep the view pinned to the latest line while the banner scrolls away.
    const totalRows = homeHeight + chatLines.length;
    const maxScroll = Math.max(0, totalRows - viewHeight);
    const offset = Math.min(scrollOffset, maxScroll);
    const topRow = maxScroll - offset;
    const showHome = topRow < homeHeight || homeHeight === 0;
    const firstChatLine = Math.max(0, topRow - homeHeight);
    const visibleLines = chatLines.slice(firstChatLine, firstChatLine + viewHeight);
    // Functional update: bursts of wheel/arrow events arrive before a re-render, so each
    // must build on the previous one rather than on this render's `offset`.
    const scrollBy = (delta: number) =>
        // No upper clamp here: maxScroll can change as the view resizes; the render-time
        // clamp (`offset`) handles overshoot.
        setScrollOffset((o) => Math.max(0, Math.min(o, maxScroll) + delta));

    // Maps a click/drag on scrollbar row `y` (1-based, chat starts at the top row) to a scroll position.
    const scrollToRow = (y: number) => {
        const fraction = viewHeight > 1 ? Math.min(1, Math.max(0, (y - 1) / (viewHeight - 1))) : 1;
        setScrollOffset(maxScroll - Math.round(fraction * maxScroll));
    };

    const handleMouse = (data: string) => {
        for (const [, rawButton, rawX, rawY, kind] of data.matchAll(MOUSE_EVENT)) {
            const button = Number(rawButton);
            const x = Number(rawX);
            const y = Number(rawY);
            if (button === 64) scrollBy(WHEEL_STEP);
            else if (button === 65) scrollBy(-WHEEL_STEP);
            else if (kind === "M" && button === 0 && y === size.rows - inputHeight) setShowSteps((v) => !v);
            else if (kind === "M" && (button === 0 || button === 32) && x >= size.columns - SCROLLBAR_WIDTH && y <= viewHeight) {
                scrollToRow(y);
            }
        }
    };

    const matchingCommands = input.startsWith("/") && !input.includes(" ")
        ? COMMANDS.filter((c) => c.name.startsWith(input))
        : [];
    const menuOpen = !picker && matchingCommands.length > 0;

    const pushEntry = useCallback((entry: ChatEntryDraft) => {
        entryIdRef.current += 1;
        setEntries((prev) => [...prev, { ...entry, id: `e${entryIdRef.current}` }]);
    }, []);

    const cancelRun = useCallback(() => {
        if (!abortRef.current || abortRef.current.signal.aborted) return;
        setStatusText("cancelling…");
        abortRef.current.abort();
    }, []);

    // A run cancelled mid tool call leaves an AI message whose tool_calls have no
    // ToolMessage answers, which the model API rejects on the next turn — answer them.
    const closeDanglingToolCalls = useCallback(async (id: string) => {
        const config = { configurable: { thread_id: id } };
        const snapshot = await orchestratorAgent.graph.getState(config);
        const messages = ((snapshot.values as { messages?: BaseMessage[] }).messages ?? []);
        const answered = new Set(messages.filter(ToolMessage.isInstance).map((m) => m.tool_call_id));
        const last = [...messages].reverse().find(AIMessage.isInstance);
        const dangling = (last?.tool_calls ?? []).filter((call) => call.id && !answered.has(call.id));
        if (dangling.length > 0) {
            await orchestratorAgent.graph.updateState(config, {
                messages: dangling.map((call) => new ToolMessage({
                    tool_call_id: call.id!,
                    name: call.name,
                    content: "Cancelled by the user before this tool finished.",
                })),
            });
        }
        seenCountRef.current = messages.length + dangling.length;
    }, []);

    const quit = useCallback(() => {
        opikHandler.flushAsync().finally(() => exit());
    }, [exit]);

    const resetView = useCallback((drafts: ChatEntryDraft[], messageCount: number) => {
        setEntries(drafts.map((d, i) => ({ ...d, id: `e${entryIdRef.current + i + 1}` })));
        entryIdRef.current += drafts.length;
        setScrollOffset(0);
        seenCountRef.current = messageCount;
    }, []);

    const startNewSession = useCallback(() => {
        setThreadId(newThreadId());
        resetView([], 0);
        setContextTokens(0);
    }, [resetView]);

    const openSession = useCallback(async (id: string) => {
        const snapshot = await orchestratorAgent.graph.getState({ configurable: { thread_id: id } });
        const messages = ((snapshot.values as { messages?: BaseMessage[] }).messages ?? []);
        setThreadId(id);
        resetView(messagesToEntries(messages), messages.length);
        setContextTokens(countContextTokens(messages));
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
            case "/mouse":
                pushEntry({ role: "status", notice: true, text: mouseEnabled
                    ? "mouse mode off · wheel/touchpad scroll via ↑/↓, text selection works"
                    : "mouse mode on · scrollbar click/drag and wheel reported by the terminal (if it supports it); shift+drag to select text" });
                setMouseEnabled(!mouseEnabled);
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
    }, [quit, startNewSession, pushEntry, mouseEnabled]);

    const handleSubmit = useCallback(async (text: string) => {
        if (runCommand(text)) return;

        setScrollOffset(0);
        pushEntry({ role: "user", text });
        touchSession(threadId, text);
        seenCountRef.current += 1;
        setIsProcessing(true);
        setStatusText("thinking…");
        const controller = new AbortController();
        abortRef.current = controller;
        let steered = false;

        try {
            const stream = await orchestratorAgent.stream(
                { messages: [new HumanMessage(text)] },
                {
                    signal: controller.signal,
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
                setContextTokens(countContextTokens(messages));
                if (messages.length > seenCountRef.current) {
                    const newMessages = messages.slice(seenCountRef.current);
                    seenCountRef.current = messages.length;

                    for (const entry of messagesToEntries(newMessages)) {
                        pushEntry(entry);
                        if (entry.role === "status") setStatusText(entry.text);
                    }
                }

                // Safe steering point: the tools step has finished and been checkpointed, so every
                // tool call is answered and nothing in flight is lost. Stop here and redirect.
                if (steerRef.current.length > 0 && ToolMessage.isInstance(messages.at(-1))) {
                    steered = true;
                    setStatusText("steering…");
                    controller.abort();
                    break;
                }
            }
        } catch (error) {
            if (steered) {
                // The abort we triggered ourselves to steer — not a user cancel or an error.
            } else if (controller.signal.aborted) {
                setQueue([]);
                steerRef.current = [];
                pushEntry({ role: "status", notice: true, text: "■ run cancelled" });
                await closeDanglingToolCalls(threadId).catch(() => {});
            } else {
                steerRef.current = [];
                pushEntry({ role: "error", text: error instanceof Error ? error.message : String(error) });
            }
        } finally {
            if (steered) {
                pushEntry({ role: "status", notice: true, text: "↪ steering after the last tool call" });
                await closeDanglingToolCalls(threadId).catch(() => {});
            }
            abortRef.current = null;
            setIsProcessing(false);
            setStatusText("");
        }

        // Deliver steering text: after a steered stop, or typed too late to catch a tool
        // boundary (the run finished first). Cancels and errors cleared it above.
        const steerText = steerRef.current.splice(0).join("\n\n");
        if (steerText) void handleSubmit(steerText);
    }, [threadId, pushEntry, runCommand]);

    useEffect(() => {
        if (isProcessing || queue.length == 0) return;
        const next = queue.join("\n\n");
        setQueue([]);
        void handleSubmit(next);
    }, [isProcessing, queue, handleSubmit]);

    useInput((char, key) => {
        if (DEBUG_INPUT_FILE) appendFileSync(DEBUG_INPUT_FILE, `${JSON.stringify({ char, key })}\n`);

        // Ctrl+C / Esc cancel a running agent; Ctrl+C when idle quits.
        if (key.ctrl && char === "c") {
            if (isProcessing) cancelRun();
            else quit();
            return;
        }
        if (key.ctrl && char === "o") {
            setShowSteps((v) => !v);
            return;
        }
        if (key.escape && isProcessing) {
            cancelRun();
            return;
        }
        // Terminal replies to control queries (e.g. the keyboard-protocol reply "[?0u")
        // can arrive late and be delivered as typed input; never put them in the box.
        if (TERMINAL_REPLY.test(char)) return;
        if (MOUSE_EVENT.test(char)) {
            MOUSE_EVENT.lastIndex = 0;
            handleMouse(char);
            return;
        }
        // Plain ↑/↓ scroll the chat unless a menu is using them. Many terminals (e.g. on
        // Windows) also translate the mouse wheel into ↑/↓ on the alternate screen.
        const arrowsScroll = !picker && !menuOpen;
        const page = Math.max(1, viewHeight - 1);
        if (key.pageUp) { scrollBy(page); return; }
        if (key.pageDown) { scrollBy(-page); return; }
        if (key.home && key.ctrl) { scrollBy(maxScroll); return; }
        if (key.end && key.ctrl) { scrollBy(-maxScroll); return; }
        if (key.upArrow && (key.shift || arrowsScroll)) { scrollBy(1); return; }
        if (key.downArrow && (key.shift || arrowsScroll)) { scrollBy(-1); return; }
        if (isProcessing && picker) return;

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
                const name = matchingCommands[selected]!.name;
                setMenuIndex(0);
                if (name == "/queue" || name == "/steer") {setInput(name); return;}
                if (isProcessing && name !== "/mouse") {
                    pushEntry({ role: "status", notice: true, text: `${name} is unavailable while the agent is working · esc to cancel first` });
                    setInput("");
                    return;
                }
                setInput("");
                runCommand(name);
                return;
            }
        }

        // Newline: shift+enter / alt+enter, ctrl+j (sends a bare "\n"), or a trailing "\" before enter.
        if ((key.return && (key.shift || key.meta)) || char === "\n") {
            insertText("\n");
            return;
        }
        if (key.return && input[editor.cursor - 1] === "\\") {
            setEditor(({ text, cursor }) => ({ text: text.slice(0, cursor - 1) + "\n" + text.slice(cursor), cursor }));
            return;
        }
        if (key.return) {
            const trimmed = input.trim();
            if (trimmed.startsWith("/queue")) {
                const message = trimmed.slice("/queue".length).trim();
                if (message) setQueue((q) => [...q, message]);
                else pushEntry({role: "status", notice: true, text: "usage /queue <message>"});
                setInput("");
                return;
            }
            else if (trimmed.startsWith("/steer")) {
                const message = trimmed.slice("/steer".length).trim();
                if (!message) pushEntry({role: "status", notice: true, text: "usage /steer <message>"});
                else if (isProcessing) {
                    steerRef.current.push(message);
                    pushEntry({role: "status", notice: true, text: `↪ will steer after the next tool call: ${message}`});
                }
                else void handleSubmit(message);
                setInput("");
                return;
            }
            if (isProcessing) {
                pushEntry({role: "status", notice: true, text: "agent is busy - use /queue <message> to run it after the agent finished. Or use /steer <message> to steer after the next tool call"});
                return;
            }
            if (trimmed.length > 0) {
                setInput("");
                void handleSubmit(trimmed);
            }
            return;
        }
        if (key.backspace) {
            setEditor(({ text, cursor }) => cursor === 0 ? { text, cursor }
                : { text: text.slice(0, cursor - 1) + text.slice(cursor), cursor: cursor - 1 });
            setMenuIndex(0);
            return;
        }
        if (key.delete) {
            setEditor(({ text, cursor }) => ({ text: text.slice(0, cursor) + text.slice(cursor + 1), cursor }));
            setMenuIndex(0);
            return;
        }

        // Cursor movement: ←/→ by character, ctrl/alt+←/→ by word, Home/End (or ctrl+a/e)
        // to the start/end of the current line.
        if (key.leftArrow) { moveCursor(({ text, cursor }) => key.ctrl || key.meta ? wordLeft(text, cursor) : cursor - 1); return; }
        if (key.rightArrow) { moveCursor(({ text, cursor }) => key.ctrl || key.meta ? wordRight(text, cursor) : cursor + 1); return; }
        if (key.home || (key.ctrl && char === "a")) { moveCursor(({ text, cursor }) => lineStart(text, cursor)); return; }
        if (key.end || (key.ctrl && char === "e")) { moveCursor(({ text, cursor }) => lineEnd(text, cursor)); return; }

        if (key.ctrl || key.meta || key.escape || key.upArrow || key.downArrow || key.tab) return;
        if (char) {
            // Pasted multi-line text arrives in one chunk with "\r" line breaks.
            insertText(char.replace(/\r\n?/g, "\n"));
            setMenuIndex(0);
        }
    });

    return (
        <Box flexDirection="column" height={size.rows}>
            <Box flexGrow={1} flexShrink={1}>
                <Box ref={chatRef} flexDirection="column" flexGrow={1} flexShrink={1} overflow="hidden">
                    {showHome && (
                        <Box ref={homeRef} flexDirection="column" flexShrink={0} marginTop={-topRow} paddingBottom={1}>
                            <Home threadId={threadId} model={MODELS.MAIN_ORCHESTRATOR_MODEL} version={version} cwd={cwd} />
                        </Box>
                    )}
                    {visibleLines.map((line, i) => (
                        <Box key={i} flexShrink={0}>
                            <Text wrap="truncate-end">{line || " "}</Text>
                        </Box>
                    ))}
                </Box>
                <Scrollbar height={viewHeight} total={totalRows} offset={offset} />
            </Box>
            <Box flexDirection="column" flexShrink={0}>
                {isProcessing && (
                    <Box gap={1}>
                        <Spinner />
                        <Text color="yellow">{statusText || "working…"}</Text>
                        <Text dimColor>· esc to cancel</Text>
                    </Box>
                )}
                {queue.map((msg, i) => (
                    <Text key={i} color="cyanBright" wrap="truncate-end">⏳ {msg}</Text>
                ))}
                {picker && (
                    <SessionPicker sessions={picker.sessions} selected={picker.selected} currentId={threadId} pendingDeleteId={pendingDeleteId} />
                )}
                {menuOpen && <CommandMenu commands={matchingCommands} selected={Math.min(menuIndex, matchingCommands.length - 1)} />}
                <StepsToggle shown={showSteps} />
                <Box ref={inputRef} flexDirection="column">
                    <InputBox editor={editor} disabled={picker !== null} />
                    <ContextBar used={contextTokens} max={contextWindow} cost={totalCost} />
                </Box>
            </Box>
        </Box>
    );
}
