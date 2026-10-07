import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdirSync } from "node:fs";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { DatabaseSync } from "node:sqlite";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { OpenRouter } from "@openrouter/sdk";
import { dataPaths } from "./paths.js";

const run = promisify(execFile);

const dbs = new Map<string, DatabaseSync>();

// One connection per resolved path (DATA_ROOT can change between eval runs).
function getDb(): DatabaseSync {
    const path = dataPaths.transcriptsDb();
    let db = dbs.get(path);
    if (!db) {
        mkdirSync(dirname(path), { recursive: true });
        db = new DatabaseSync(path);
        db.exec(`CREATE TABLE IF NOT EXISTS transcripts (
            platform       TEXT NOT NULL,
            video_id       TEXT NOT NULL,
            url            TEXT NOT NULL,
            model          TEXT NOT NULL,
            text           TEXT NOT NULL,
            transcribed_at TEXT NOT NULL,
            PRIMARY KEY (platform, video_id)
        )`);
        dbs.set(path, db);
    }
    return db;
}

function readCached(platform: Platform, videoId: string): Transcript | undefined {
    const row = getDb()
        .prepare("SELECT platform, video_id, url, model, text, transcribed_at FROM transcripts WHERE platform = ? AND video_id = ?")
        .get(platform, videoId) as { platform: Platform; video_id: string; url: string; model: string; text: string; transcribed_at: string } | undefined;
    if (!row || row.model !== STT_MODEL) return undefined;
    return { platform: row.platform, videoId: row.video_id, url: row.url, model: row.model, text: row.text, transcribedAt: row.transcribed_at };
}

function saveTranscript(t: Transcript): void {
    getDb()
        .prepare("INSERT OR REPLACE INTO transcripts (platform, video_id, url, model, text, transcribed_at) VALUES (?, ?, ?, ?, ?, ?)")
        .run(t.platform, t.videoId, t.url, t.model, t.text, t.transcribedAt);
}

const STT_MODEL = "nvidia/nemotron-3.5-asr-streaming-multilingual-0.6b";
const CONCURRENCY = 3;

export type Platform = "tiktok" | "instagram";

export interface Transcript {
    platform: Platform;
    videoId: string;
    url: string;
    model: string;
    text: string;
    transcribedAt: string;
}

export type TranscriptResult =
    | { url: string; ok: true; cached: boolean; transcript: Transcript }
    | { url: string; ok: false; error: string };

function detectPlatform(url: string): Platform {
    const host = new URL(url).hostname;
    if (host.endsWith("instagram.com")) return "instagram";
    if (host.endsWith("tiktok.com")) return "tiktok";
    throw new Error("Unsupported platform — only Tiktok and Instagram URLs can be transcribed");
}

// Instagram logins: yt-dlp usually needs a logged-in session for reels. Point
// YTDLP_COOKIES_FILE at a Netscape-format cookies.txt exported from a browser.
function cookieArgs(): string[] {
    const file = process.env["YTDLP_COOKIES_FILE"];
    return file ? ["--cookies", file] : [];
}

async function resolveVideoId(platform: Platform, url: string): Promise<string> {
    // Full URLs carry the id; Tiktok short links (vm.tiktok.com/...) need a metadata-only lookup.
    const match = platform === "instagram"
        ? url.match(/\/(?:reels?|p|tv)\/([\w-]+)/)
        : url.match(/\/video\/(\d+)/);
    if (match?.[1]) return match[1];
    const { stdout } = await run("yt-dlp", ["--no-playlist", ...cookieArgs(), "--print", "id", url]);
    return stdout.trim();
}

// Downloads only the audio track as 16 kHz mono wav (what the STT models use internally).
async function downloadAudio(url: string, dir: string): Promise<string> {
    await run("yt-dlp", [
        "--no-playlist",
        ...cookieArgs(),
        "-x", "--audio-format", "wav",
        "--postprocessor-args", "ffmpeg:-ac 1 -ar 16000",
        "-o", join(dir, "%(id)s.%(ext)s"),
        url,
    ]);
    const file = (await readdir(dir)).find((f) => f.endsWith(".wav"));
    if (!file) throw new Error("yt-dlp produced no audio file");
    return join(dir, file);
}

async function transcribeOne(url: string): Promise<TranscriptResult> {
    try {
        const platform = detectPlatform(url);
        const videoId = await resolveVideoId(platform, url);
        const cached = readCached(platform, videoId);
        if (cached) return { url, ok: true, cached: true, transcript: cached };

        const tmp = await mkdtemp(join(tmpdir(), "video-audio-"));
        try {
            const audioPath = await downloadAudio(url, tmp);
            const data = (await readFile(audioPath)).toString("base64");
            const openRouter = new OpenRouter({ apiKey: process.env["OPENROUTER_API_KEY"] ?? "" });
            const res = await openRouter.stt.createTranscription({
                sttRequest: { inputAudio: { data, format: "wav" }, model: STT_MODEL },
            });

            const transcript: Transcript = {
                platform,
                videoId,
                url,
                model: STT_MODEL,
                text: res.text,
                transcribedAt: new Date().toISOString(),
            };
            saveTranscript(transcript);
            return { url, ok: true, cached: false, transcript };
        } finally {
            await rm(tmp, { recursive: true, force: true });
        }
    } catch (error) {
        return { url, ok: false, error: error instanceof Error ? error.message : String(error) };
    }
}

// Transcribes each URL (cache-first), CONCURRENCY at a time. One failure never fails the batch.
export async function transcribeVideoUrls(urls: string[]): Promise<TranscriptResult[]> {
    const unique = [...new Set(urls)];
    const results: TranscriptResult[] = new Array(unique.length);
    let next = 0;
    const worker = async () => {
        while (next < unique.length) {
            const i = next++;
            results[i] = await transcribeOne(unique[i]!);
        }
    };
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, unique.length) }, worker));
    return results;
}
