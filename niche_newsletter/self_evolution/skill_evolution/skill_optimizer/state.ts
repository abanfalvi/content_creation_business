import { z } from "zod";
import { StateSchema, ReducedValue, MessagesValue } from "@langchain/langgraph";
import type { Transcript } from "../trace_transcript.js"
import type { AgentName } from "../../../eval/problems/types.js";

type createdSkills = {
  skillPaths: string[],
  skillFileContents: string[]
};

export const skillOptimizerState = new StateSchema({
  suiteId: z.string(),
  agentName: z.custom<AgentName>(),
  // Prebuilt messages value
  traceTranscript: z.custom<Transcript>(),
  // ReducedValue for fields needing reducers
  history: new ReducedValue(
    z.array(z.string()).default(() => []),
    {
      inputSchema: z.string(),
      reducer: (current, next) => [...current, next],
    }
  ),
  traceSummary: z.string().default(""),
  optimizerActions: z.string().default(""),
  regressionPass: z.boolean().default(false),
  regressionReport: z.string().default(""),
});