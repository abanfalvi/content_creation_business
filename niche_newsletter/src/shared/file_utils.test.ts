import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { applyFindAndReplace, findAndReplace, normalizeNewlines, readOrInitFile } from "./file_utils.js";

// Creates a fresh temp directory for a test and registers its cleanup, so
// filesystem-touching tests stay hermetic instead of depending on (or mutating)
// real project files.
async function useTempDir(t: import("node:test").TestContext): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), "file-utils-test-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return dir;
}

test("normalizeNewlines converts CRLF to LF", () => {
  assert.equal(normalizeNewlines("a\r\nb\r\nc"), "a\nb\nc");
});

test("findAndReplace replaces a unique exact match", () => {
  const result = findAndReplace("hello world", "world", "there");
  assert.deepEqual(result, { status: "ok", result: "hello there" });
});

test("findAndReplace reports not_found when the text is absent", () => {
  const result = findAndReplace("hello world", "missing", "x");
  assert.deepEqual(result, { status: "not_found" });
});

test("findAndReplace reports ambiguous when the text matches more than once", () => {
  const result = findAndReplace("foo foo foo", "foo", "bar");
  assert.deepEqual(result, { status: "ambiguous", count: 3 });
});

test("findAndReplace tolerates smart-quote and whitespace differences", () => {
  const content = 'She said “hi   there”.';
  const result = findAndReplace(content, "She said \"hi there\".", "Replaced.");
  assert.deepEqual(result, { status: "ok", result: "Replaced." });
});

test("applyFindAndReplace writes the replacement to disk on a unique match", async (t) => {
  const dir = await useTempDir(t);
  const filePath = join(dir, "notes.md");
  await writeFile(filePath, "## Findings\nfoo is the key insight.", "utf-8");

  const outcome = await applyFindAndReplace(filePath, "foo is the key insight.", "bar is the key insight.");

  assert.deepEqual(outcome, { status: "ok", result: "## Findings\nbar is the key insight." });
  assert.equal(await readFile(filePath, "utf-8"), "## Findings\nbar is the key insight.");
});

test("applyFindAndReplace leaves the file untouched when the match is ambiguous", async (t) => {
  const dir = await useTempDir(t);
  const filePath = join(dir, "notes.md");
  const original = "foo foo foo";
  await writeFile(filePath, original, "utf-8");

  const outcome = await applyFindAndReplace(filePath, "foo", "bar");

  assert.deepEqual(outcome, { status: "ambiguous", count: 3 });
  assert.equal(await readFile(filePath, "utf-8"), original);
});

test("applyFindAndReplace leaves the file untouched when the text is not found", async (t) => {
  const dir = await useTempDir(t);
  const filePath = join(dir, "notes.md");
  const original = "unrelated content";
  await writeFile(filePath, original, "utf-8");

  const outcome = await applyFindAndReplace(filePath, "missing text", "replacement");

  assert.deepEqual(outcome, { status: "not_found" });
  assert.equal(await readFile(filePath, "utf-8"), original);
});

test("applyFindAndReplace creates a missing file with default content, then reports not_found", async (t) => {
  const dir = await useTempDir(t);
  const filePath = join(dir, "new_notes.md");

  const outcome = await applyFindAndReplace(filePath, "some text", "replacement");

  assert.deepEqual(outcome, { status: "not_found" });
  assert.equal(await readFile(filePath, "utf-8"), " ");
});

test("readOrInitFile returns existing content without modifying the file", async (t) => {
  const dir = await useTempDir(t);
  const filePath = join(dir, "existing.md");
  await writeFile(filePath, "already here", "utf-8");

  const content = await readOrInitFile(filePath);

  assert.equal(content, "already here");
  assert.equal(await readFile(filePath, "utf-8"), "already here");
});

test("readOrInitFile creates the file with the given initial content when missing", async (t) => {
  const dir = await useTempDir(t);
  const filePath = join(dir, "missing.md");

  const content = await readOrInitFile(filePath, "# New notes\n");

  assert.equal(content, "# New notes\n");
  assert.equal(await readFile(filePath, "utf-8"), "# New notes\n");
});
