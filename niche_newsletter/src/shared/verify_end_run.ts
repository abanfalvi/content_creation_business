import { createMiddleware } from "langchain";
import { HumanMessage } from "@langchain/core/messages";
import { OpenRouter } from "@openrouter/sdk";
import type { DecisionsRequest } from "@openrouter/sdk/models";
import { MODELS } from "../models.js";

const decisionsClient = new OpenRouter({ apiKey: process.env.OPENROUTER_API_KEY ?? "" });
type DecisionsQuestions = DecisionsRequest["questions"];

const LC_SOURCE = "end_run_verfication";
const FINISHED_THRESHOLD = 0.5;
const MAX_NUDGES = 2;

const END_VERIFICATION_QUESTION = {
  finishedWithReport: {
    type: "noul",
    instructions:
      "Did the agent finish its run with a message explaining what it has done? Whether this is confirming the task is done or raising an issues.",
    criteria: {
      true: "The agent confirmed it had finished the task or raised an issue",
      false: "The agent did not return anything",
    },
  },
} satisfies DecisionsQuestions;

/**
 * Judges the agent's last message when it tries to end its run; if it doesn't read as a finished
 * report (or a raised issue), nudges the agent back to the model, at most MAX_NUDGES times per run.
 */
export function createVerifyEndRunMiddleware() {
  return createMiddleware({
    name: "verify_end_run_middleware",

    afterAgent: {
      canJumpTo: ["model"],
      hook: async (state) => {
        const nudges = state.messages.filter(
          (m) => HumanMessage.isInstance(m) && m.additional_kwargs?.lc_source === LC_SOURCE,
        ).length;
        if (nudges >= MAX_NUDGES) return {};

        const lastMessage = state.messages.at(-1)?.content;
        try {
          const response = await decisionsClient.alpha.decisions.create({
            decisionsRequest: {
              model: MODELS.OVERLAP_JUDGE_MODEL,
              questions: END_VERIFICATION_QUESTION,
              state: { lastAgentMessage: lastMessage },
            },
          });
          const answer = response.answers.finishedWithReport;
          const score = answer?.type === "noul" ? answer.noul : undefined;
          if (score === undefined || score > FINISHED_THRESHOLD) return {};

          const returnMessage =
            "Your last message seems unfinished. Verify you completed the tasks you were given. If yes, confirm it in your response or raise any issue you had, else keep working on it.";
          return {
            messages: [new HumanMessage({ content: returnMessage, additional_kwargs: { lc_source: LC_SOURCE } })],
            jumpTo: "model" as const,
          };
        } catch (error) {
          // Fail open: a judge failure never blocks or steers the agent.
          console.warn(`[end_run judge] skipped: ${String(error)}`);
          return {};
        }
      },
    },
  });
}
