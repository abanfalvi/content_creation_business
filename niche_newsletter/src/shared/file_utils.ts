// Shared local-file read/write/edit helpers for agent tools that keep a working file
// (scratch pad notes, todo lists, how-to drafts, ...) on disk. Import from here instead
// of re-implementing find-and-replace or read/create-on-missing logic per agent.

import { mkdir, readFile, writeFile, appendFile } from "fs/promises";
import { dirname } from "path";

// Normalize CRLF to LF so a to_replace written with \n still matches a Windows-line-ended file.
export const normalizeNewlines = (s: string) => s.replace(/\r\n/g, "\n");

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// Any of these count as "the same quote" for matching purposes — scraped web content
// commonly uses curly/smart quotes where a model writes straight ones, or vice versa.
const SINGLE_QUOTES = `'‘’‚‛`;
const DOUBLE_QUOTES = `"“”„‟`;
const SINGLE_QUOTE_CLASS = `[${SINGLE_QUOTES}]`;
const DOUBLE_QUOTE_CLASS = `[${DOUBLE_QUOTES}]`;

// Collapses runs of whitespace in the target into `\s+`, and any quote character into
// a class matching all straight/curly variants, so indentation/line-break differences
// and quote-style mismatches between what the model wrote and the file's actual
// content don't block an otherwise-correct match.
const buildFlexiblePattern = (s: string) =>
  new RegExp(
    escapeRegExp(s)
      .replace(new RegExp(`[${SINGLE_QUOTES}]`, "g"), SINGLE_QUOTE_CLASS)
      .replace(new RegExp(`[${DOUBLE_QUOTES}]`, "g"), DOUBLE_QUOTE_CLASS)
      .replace(/\s+/g, "\\s+"),
    "g"
  );

export type FindAndReplaceResult =
  | { status: "ok"; result: string }
  | { status: "not_found" }
  | { status: "ambiguous"; count: number };

// Tries an exact substring match first (fast, unambiguous); if that finds nothing,
// falls back to a whitespace-tolerant regex match before giving up.
export function findAndReplace(content: string, to_replace: string, replace_with: string): FindAndReplaceResult {
  const exactCount = content.split(to_replace).length - 1;
  if (exactCount === 1) {
    return { status: "ok", result: content.replaceAll(to_replace, replace_with) };
  }
  if (exactCount > 1) {
    return { status: "ambiguous", count: exactCount };
  }

  const flexiblePattern = buildFlexiblePattern(to_replace);
  const flexCount = content.match(flexiblePattern)?.length ?? 0;
  if (flexCount === 0) {
    return { status: "not_found" };
  }
  if (flexCount > 1) {
    return { status: "ambiguous", count: flexCount };
  }
  return { status: "ok", result: content.replace(flexiblePattern, replace_with) };
}

export async function ensureDirFor(filePath: string): Promise<void> {
  await mkdir(dirname(filePath), { recursive: true });
}

export async function writeFileEnsuringDir(filePath: string, content: string): Promise<void> {
  await ensureDirFor(filePath);
  await writeFile(filePath, content, "utf-8");
}

export async function appendFileEnsuringDir(filePath: string, content: string): Promise<void> {
  await ensureDirFor(filePath);
  await appendFile(filePath, content, "utf-8");
}

// Reads a file, creating it (and its parent directory) with `initialContent` if it doesn't exist yet.
export async function readOrInitFile(filePath: string, initialContent = " "): Promise<string> {
  await ensureDirFor(filePath);
  try {
    return await readFile(filePath, "utf-8");
  } catch {
    await writeFile(filePath, initialContent, "utf-8");
    return initialContent;
  }
}

// Applies a find-and-replace edit to a file (creating it via readOrInitFile if missing),
// normalizing CRLF and tolerating whitespace/quote differences between `to_replace` and the
// file's actual content. Writes the file only when the edit is unambiguous; leaves it
// untouched otherwise so callers can turn the returned status into a tool message.
export async function applyFindAndReplace(
  filePath: string,
  to_replace: string,
  replace_with: string,
  initialContent = " "
): Promise<FindAndReplaceResult> {
  const content = normalizeNewlines(await readOrInitFile(filePath, initialContent));
  const outcome = findAndReplace(content, normalizeNewlines(to_replace), normalizeNewlines(replace_with));
  if (outcome.status === "ok") {
    await writeFile(filePath, outcome.result, "utf-8");
  }
  return outcome;
}
