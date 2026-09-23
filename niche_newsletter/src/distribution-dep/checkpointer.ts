import { SqliteSaver } from "@langchain/langgraph-checkpoint-sqlite";
import { dataPaths } from "../shared/paths.js";

export const checkpointer = SqliteSaver.fromConnString(dataPaths.checkpointDb("distribution-dep"));
