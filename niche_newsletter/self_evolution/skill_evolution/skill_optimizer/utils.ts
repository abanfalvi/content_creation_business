import type { SkillEvalItemData } from "../trace_schema.js";

export function isSkillEvalData(value: unknown): value is SkillEvalItemData {
    const data = value as Partial<SkillEvalItemData> | null;
    return typeof data === "object" && data !== null && data.schemaVersion === 1 && typeof data.replay?.input === "string";
}