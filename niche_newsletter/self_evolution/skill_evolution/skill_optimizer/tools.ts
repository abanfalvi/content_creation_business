import { tool } from "langchain";

const listResearchTopics = tool(
    async () => {
        

    }, {
        name: "list_research_topics",
        description: "Use this to get the list of research topics that have been executed previously to be able to keep working on it"
    }
)