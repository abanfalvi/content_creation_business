import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { render } from "ink";
import { App } from "./App.js";

function parseThreadId(argv: string[]): string {
    const flagIndex = argv.findIndex((arg) => arg === "--thread" || arg === "-t");
    const explicitId = flagIndex !== -1 ? argv[flagIndex + 1] : undefined;
    return explicitId ?? randomUUID().slice(0, 8);
}

function readVersion(): string {
    const __dirname = path.dirname(fileURLToPath(import.meta.url));
    const packageJsonPath = path.join(__dirname, "..", "..", "package.json");
    const pkg = JSON.parse(readFileSync(packageJsonPath, "utf-8")) as { version?: string };
    return pkg.version ?? "0.0.0";
}

const threadId = parseThreadId(process.argv.slice(2));
const version = readVersion();
const cwd = process.cwd();

const instance = render(<App threadId={threadId} version={version} cwd={cwd} />, { alternateScreen: true });

instance.waitUntilExit()
    .then(() => process.exit(0))
    .catch((error: unknown) => {
        console.error(error);
        process.exit(1);
    });
