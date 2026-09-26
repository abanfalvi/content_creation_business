import { mkdir, mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, relative, sep } from "node:path";
import { writeFileEnsuringDir } from "../../src/shared/file_utils.js";
import { dataPaths } from "../../src/shared/paths.js";

export const notesPath = (topic: string) => join(dataPaths.researchScratchPad(), `${topic}_notes.md`);
export const useCasesPath = (topic: string) => join(dataPaths.useCaseScratchPad(), `${topic}_use_cases.md`);
export const strategyPath = (name: string) => join(dataPaths.contentStrategy(), `${name}.md`);
export const memoryPath = (relative: string) => join(dataPaths.memories(), relative);

// Findings 1, 2 and 6 are keepers (6 is hype-padded and lacks a how-to, so it should be
// salvaged, not cut). 3 duplicates 1, 4 is unsourced, 5 is off-topic.
export const RAW_NOTES_WITH_PLANTED_FLAWS = `# Research notes: LLM output validation

## Finding 1: Structured Outputs guarantee schema-conformant JSON
What happened: OpenAI added Structured Outputs to its API in August 2024. Setting "strict": true on a json_schema response format constrains generation so the output always matches the supplied JSON Schema. On OpenAI's complex-schema eval, gpt-4o-2024-08-06 with Structured Outputs scored 100%, versus under 40% for gpt-4-0613.
Why it's relevant: Malformed JSON is one of the most common failure points when LLM output feeds another program.
How to use it: Define the expected output as a JSON Schema (or a Pydantic/Zod model), pass it with strict mode enabled, and drop the retry-on-parse-error loop.
Source: https://openai.com/index/introducing-structured-outputs-in-the-api/

## Finding 2: LLM-as-a-judge agrees with human raters about as often as humans agree with each other
What happened: Zheng et al. (2023) found strong LLM judges such as GPT-4 reach over 80% agreement with human preferences, the same level as agreement between humans. They also documented judge biases: position bias, verbosity bias and self-enhancement bias.
Why it's relevant: Grading open-ended output by hand doesn't scale; an LLM judge makes routine quality checks affordable.
How to use it: Write a rubric, have a strong model grade each output against it, swap answer order to control position bias, and spot-check a sample against human ratings.
Source: https://arxiv.org/abs/2306.05685

## Finding 3: OpenAI docs cover structured outputs
What happened: The OpenAI platform documentation has a guide for structured outputs using JSON schemas.
Why it's relevant: Helps get JSON out of models.
How to use it: Read the guide.
Source: https://platform.openai.com/docs/guides/structured-outputs

## Finding 4: Secret validation prompt cuts hallucinations by 90%
What happened: A startup reportedly eliminated 90% of hallucinations with a single validation prompt it has not disclosed.
Why it's relevant: Hallucinations are the biggest blocker to production AI.
How to use it: Add a validation prompt to your pipeline.

## Finding 5: Anthropic launched the Model Context Protocol
What happened: In November 2024 Anthropic open-sourced the Model Context Protocol (MCP), a standard for connecting AI assistants to data sources and tools.
Why it's relevant: Reduces custom integration work for AI apps.
How to use it: Use an existing MCP server to connect your assistant to a data source.
Source: https://www.anthropic.com/news/model-context-protocol

## Finding 6: Self-consistency is an absolutely game-changing, revolutionary breakthrough
What happened: In an incredible, jaw-dropping result, Wang et al. (2022) showed that sampling many reasoning paths and taking the majority-vote answer massively improves accuracy — +17.9% on GSM8K with PaLM 540B. This changes everything about AI.
Why it's relevant: It is simply the most important technique ever discovered.
Source: https://arxiv.org/abs/2203.11171
`;

export const CLEAN_NOTES = `---
index:
  - structured_outputs: Schema-guaranteed JSON via strict mode
  - llm_as_judge: Rubric-based grading by a strong model
  - self_consistency: Majority vote across sampled reasoning paths
---
# Research notes: LLM output validation

## Finding 1: Structured Outputs guarantee schema-conformant JSON
What happened: OpenAI added Structured Outputs to its API in August 2024. Setting "strict": true on a json_schema response format constrains generation to the supplied JSON Schema. On OpenAI's complex-schema eval, gpt-4o-2024-08-06 with Structured Outputs scored 100%, versus under 40% for gpt-4-0613.
Why it's relevant: Malformed JSON is a common failure point when LLM output feeds another program.
How to use it: Define the expected output as a JSON Schema (or Pydantic/Zod model), enable strict mode, and remove parse-error retry loops.
Source: https://openai.com/index/introducing-structured-outputs-in-the-api/

## Finding 2: LLM-as-a-judge matches human agreement levels
What happened: Zheng et al. (2023) found strong LLM judges such as GPT-4 reach over 80% agreement with human preferences, similar to human-human agreement, with known position, verbosity and self-enhancement biases.
Why it's relevant: Makes routine grading of open-ended output affordable.
How to use it: Grade outputs against a written rubric with a strong model, swap answer order to control position bias, and spot-check against human ratings.
Source: https://arxiv.org/abs/2306.05685

## Finding 3: Self-consistency uses agreement across samples as a check
What happened: Wang et al. (2022) sampled multiple reasoning paths and took the majority answer, improving GSM8K accuracy by 17.9 points with PaLM 540B.
Why it's relevant: Low agreement between samples is a cheap signal that an answer is unreliable.
How to use it: Sample 5-10 answers at non-zero temperature, take the majority, and flag inputs where agreement falls below a threshold for review.
Source: https://arxiv.org/abs/2203.11171
`;

// Finding 4's claim is not demonstrated by its source; the use-case writer should flag
// or skip it rather than write it up as a tested workflow.
export const NOTES_WITH_UNVERIFIED_CLAIM = `${CLEAN_NOTES}
## Finding 4: Fully autonomous self-healing validation agent
What happened: A viral post claims an agent can validate every LLM output and automatically fix all errors with zero human review, using MCP.
Why it's relevant: Would remove humans from quality control entirely.
How to use it: Connect your pipeline to an MCP server and let the agent fix outputs automatically.
Source: https://www.anthropic.com/news/model-context-protocol
`;

export const USE_CASES = `# Use cases: LLM output validation

## Use case 1: Stop parsing failures with Structured Outputs
What it is: Force a model's reply to always match your JSON Schema.
How to do it:
1. Write the output shape as a JSON Schema (or a Zod/Pydantic model converted to one).
2. Call the Chat Completions API with response_format type "json_schema" and "strict": true.
3. Delete the retry-on-JSON-parse-error code path; keep handling refusals separately.
Evidence: OpenAI's announcement reports 100% schema adherence on its complex-schema eval for gpt-4o-2024-08-06.
Source: https://openai.com/index/introducing-structured-outputs-in-the-api/

## Use case 2: Grade outputs with an LLM judge
What it is: Score open-ended answers against a rubric using a strong model.
How to do it:
1. Write a 3-5 criterion rubric with a concrete description for each score.
2. Ask the judge model to score each output and quote evidence per criterion.
3. Run each pairwise comparison twice with the answer order swapped; discard inconsistent verdicts.
4. Every week, compare 20 judged outputs against a human rating to catch drift.
Evidence: Zheng et al. (2023) report over 80% judge-human agreement and document position bias.
Source: https://arxiv.org/abs/2306.05685
`;

export const LEAD_MAGNET_STRATEGY = `# Theme: LLM output validation for small teams

Audience: solo developers and small product teams shipping their first LLM feature.
Goal: a free downloadable checklist that earns newsletter signups.

Product: "The LLM Output Validation Checklist" — a 4-6 page PDF.
Must cover:
- Enforcing output format with schema-constrained generation (structured outputs).
- Grading quality with an LLM judge and a written rubric, including position-bias control.
- Using agreement across multiple samples (self-consistency) as a reliability signal.
- A one-page printable checklist summarizing the steps.
Tone: practical, no hype. End with a call to action to subscribe to the newsletter.
`;

// A small, well-organized memories tree. Send day is Tuesday (for the "outdated" case),
// the length memory has a sibling in /audience (for the "duplicate" case), and nothing
// covers sponsors (for the "nothing relevant" case).
export const MEMORY_TREE: Record<string, string> = {
    "audience/issue_length.md": `---
name: issue_length
description: Readers drop off after ~1,500 words — keep issues under that
updated: 2026-06-10
valid_from: 2026-06-10
valid_until: null
superseded_by: null
---

Issues over 1,500 words had a 20% lower click-through rate than shorter ones (May 2026 analytics). Keep each issue under 1,500 words.
`,
    "audience/reader_roles.md": `---
name: reader_roles
description: Who reads the newsletter — mostly engineers at small AI teams
updated: 2026-05-02
valid_from: 2026-05-02
valid_until: null
superseded_by: null
---

The April 2026 reader survey: 62% software engineers, 21% founders, 17% product managers. Most work on teams of under 10 people.
`,
    "publishing/send_schedule.md": `---
name: send_schedule
description: Issues are sent every Tuesday at 08:00 UTC
updated: 2026-03-01
valid_from: 2026-03-01
valid_until: null
superseded_by: null
---

The newsletter goes out every Tuesday at 08:00 UTC.
`,
    "style/no_hype_words.md": `---
name: no_hype_words
description: Banned hype words (game-changing, revolutionary, etc.) in all published copy
updated: 2026-04-15
valid_from: 2026-04-15
valid_until: null
superseded_by: null
---

Never use "game-changing", "revolutionary", "jaw-dropping" or "changes everything" in issues or social posts. Readers flagged these as a reason for distrust.
`,
};

// Every memory file with its full content, so the judge sees the tree the agent left behind.
export async function dumpMemoryTree(): Promise<string> {
    const root = dataPaths.memories();
    const files = (await readdir(root, { recursive: true, withFileTypes: true }).catch(() => []))
        .filter((entry) => entry.isFile())
        .map((entry) => join(entry.parentPath, entry.name));
    if (files.length === 0) return "(the memories folder is empty)";
    const sections = await Promise.all(files.sort().map(async (file) =>
        `### /${relative(root, file).split(sep).join("/")}\n${await readFile(file, "utf-8")}`,
    ));
    return sections.join("\n");
}

export async function writeFixture(path: string, content: string): Promise<void> {
    await writeFileEnsuringDir(path, content);
}

// Evals run against a throwaway DATA_ROOT, so agents never see or modify real notes,
// strategy docs, todo lists or checkpoint databases — even if the run is killed midway.
const ROOT_PREFIX = "niche-newsletter-eval-";

export async function createDataRoot(): Promise<string> {
    await sweepStaleDataRoots();
    const root = await mkdtemp(join(tmpdir(), ROOT_PREFIX));
    process.env.DATA_ROOT = root;
    // better-sqlite3 won't create missing directories for the checkpoint databases.
    for (const department of ["orchestrator", "distribution-dep", "curriculum-dep"] as const) {
        await mkdir(dirname(dataPaths.checkpointDb(department)), { recursive: true });
    }
    await resetDataDirs();
    return root;
}

// Runs before every case so each starts from empty scratch pads, strategy docs and memories.
// Checkpoint databases are left alone: they stay open for the whole process, and each
// case uses its own thread_id anyway.
export async function resetDataDirs(): Promise<void> {
    for (const dir of [dataPaths.researchScratchPad(), dataPaths.useCaseScratchPad(), dataPaths.contentStrategy(), dataPaths.memories()]) {
        await rm(dir, { recursive: true, force: true });
        await mkdir(dir, { recursive: true });
    }
}

// On Windows the open SQLite files keep the root locked until the process exits, so this
// can fail; sweepStaleDataRoots removes such leftovers at the start of the next run.
export async function removeDataRoot(root: string): Promise<boolean> {
    try {
        await rm(root, { recursive: true, force: true, maxRetries: 3 });
        return true;
    } catch {
        return false;
    }
}

async function sweepStaleDataRoots(): Promise<void> {
    const entries = await readdir(tmpdir(), { withFileTypes: true }).catch(() => []);
    for (const entry of entries) {
        if (entry.isDirectory() && entry.name.startsWith(ROOT_PREFIX)) {
            await rm(join(tmpdir(), entry.name), { recursive: true, force: true }).catch(() => undefined);
        }
    }
}
