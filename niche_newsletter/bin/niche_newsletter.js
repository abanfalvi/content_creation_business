#!/usr/bin/env node
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const entry = path.join(__dirname, "..", "src", "tui", "index.tsx");

const child = spawn(process.execPath, ["--import", "tsx", "--import", "dotenv/config", entry, ...process.argv.slice(2)], {
    stdio: "inherit",
    cwd: path.join(__dirname, ".."),
});

child.on("exit", (code) => process.exit(code ?? 0));
child.on("error", (error) => {
    console.error(error);
    process.exit(1);
});
