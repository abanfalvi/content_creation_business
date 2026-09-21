import { SqliteSaver } from "@langchain/langgraph-checkpoint-sqlite";

export const checkpointer = SqliteSaver.fromConnString("src/curriculum-dep/.checkpoints/state.db");
