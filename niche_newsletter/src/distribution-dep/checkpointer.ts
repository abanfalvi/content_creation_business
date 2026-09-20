import { SqliteSaver } from "@langchain/langgraph-checkpoint-sqlite";

export const checkpointer = SqliteSaver.fromConnString("src/distribution-dep/.checkpoints/state.db");
