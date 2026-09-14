import { readFile, writeFile } from 'fs/promises';
import { join } from 'path';

const normalizeNewlines = (s: string) => s.replace(/\r\n/g, "\n");

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

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

function findAndReplace(content: string, to_replace: string, replace_with: string):
    | { status: "ok"; result: string }
    | { status: "not_found" }
    | { status: "ambiguous"; count: number } {
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

async function editResearchFindings(to_replace: string, replace_with: string) {
    const researchTopic = "ai_marketing_automation"
        const filePath = join("src/signal-editor-dep/research_agent/scratch_pad/", `${researchTopic}_notes.md`)
        const findings = normalizeNewlines(await readFile(filePath, "utf-8"))
        const to_replace_normalized = normalizeNewlines(to_replace);
        const replace_with_normalized = normalizeNewlines(replace_with);

        const outcome = findAndReplace(findings, to_replace_normalized, replace_with_normalized);
        if (outcome.status === "not_found") {
            return `"${to_replace}" not found in file (checked exact and whitespace-flexible matches).`;
        }
        if (outcome.status === "ambiguous") {
            return `"${to_replace}" found ${outcome.count} times — expected exactly one match, aborting edit. Add more context.`;
        }

        try {
            await writeFile(filePath, outcome.result, 'utf-8');
        } catch (error) {
            return error
        }

        return "Successful edit";
};

const toReplace = `
10. Move from assisted automation to bounded agentic marketing workflows.
What happened: Adobe describes agentic marketing as AI systems that make proactive suggestions, take actions, and orchestrate personalized customer journeys; Google's 2026 marketing guidance says the field is shifting from isolated AI experiments toward integrated AI workflows and real-time data pipelines. OpenAI's practical agent guide recommends explicit limits on retries/actions and human oversight for high-risk actions.
Why it's relevant: Agentic systems can monitor campaigns and adjust journeys continuously, but uncontrolled autonomy can create brand, privacy, or customer-experience failures.
How to use it: Begin with AI-assisted recommendations or shadow mode; select one bounded use case such as report summarization, audience prioritization, or content variation; specify allowed tools/data, approval thresholds, escalation rules, retry limits, and rollback; expand autonomy only after measured reliability.
Source: https://experienceleague.adobe.com/en/perspectives/agentic-marketing-intelligent-personalization-with-ai-led-cx
Source: https://business.google.com/in/think/future-of-marketing/marketing-predictions-guide-2026
Source: https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents
`
const replaceWith = ""
console.log(editResearchFindings(toReplace, replaceWith))