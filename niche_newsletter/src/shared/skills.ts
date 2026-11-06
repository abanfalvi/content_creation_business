import { CompositeBackend, createFilesystemMiddleware, createSkillsMiddleware, FilesystemBackend } from "deepagents";
import { createMiddleware, type AnyAgentMiddleware } from "langchain";
import { dataPaths } from "./paths.js";

// Each specialist's skills live in src/skills/<agent>/<skill>/SKILL.md, and the agent sees them
// under /skills/.
export const SKILLS_ROOT = "src/skills";

// The skill optimizer's regression run points SKILLS_ROOT at a working copy of the tree, so the agents
// under test read the candidate skills while src/skills stays untouched until the candidates are approved.
// Read on every call, not at import.
export const skillsBackend = (agent: string) =>
    new FilesystemBackend({ rootDir: `${process.env.SKILLS_ROOT || SKILLS_ROOT}/${agent}`, virtualMode: true });

const RESEARCH_NOTES_PROMPT =
    "\n\n# Research notes (read-only)\n\n" +
    "Every research notes file in the system is readable under `/research_notes/` (`<topic>_notes.md`). " +
    "Use `ls`, `read_file`, `glob` and `grep` on it. You can't create or change notes, so don't try.";

const researchNotesNote = createMiddleware({
    name: "research_notes_read_only_note",
    wrapModelCall: (request, handler) =>
        handler({ ...request, systemMessage: request.systemMessage.concat(RESEARCH_NOTES_PROMPT) }),
});

// Lists the agent's skills in its system prompt and gives it read-only file tools to open them,
// the same way the orchestrator reads its skills. With `readResearchNotes`, the same tools also
// reach the research notes folder. Only ls/read_file/glob/grep are registered, so neither the skills
// nor the notes can be written through them.
// Agents that already have file tools should route "/skills/" in their own CompositeBackend and
// add only createSkillsMiddleware.
export function createSkillsMiddlewares(agent: string, { readResearchNotes = false } = {}): AnyAgentMiddleware[] {
    const skills = skillsBackend(agent);
    const backend = new CompositeBackend(skills, {
        "/skills/": skills,
        ...(readResearchNotes
            ? { "/research_notes/": new FilesystemBackend({ rootDir: dataPaths.researchScratchPad(), virtualMode: true }) }
            : {}),
    });
    return [
        createFilesystemMiddleware({ backend, tools: ["ls", "read_file", "glob", "grep"] }),
        createSkillsMiddleware({ backend, sources: ["/skills/"] }),
        ...(readResearchNotes ? [researchNotesNote] : []),
    ] as AnyAgentMiddleware[];
}
