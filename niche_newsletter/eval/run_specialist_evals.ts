import { Opik, TestSuite, type EvaluationTask, evaluate, ExactMatch } from "opik";

const client = new Opik();

const suite = await TestSuite.getOrCreate(client, {
  name: "customer-support-qa",
  projectName: "test-suites-demo",
  globalAssertions: [
    "The response is grounded in the provided documentation context",
    "The response directly addresses the user's question",
    "The response is concise (3 sentences or fewer)",
  ],
  globalExecutionPolicy: { runsPerItem: 2, passThreshold: 2 },
});

await suite.insert([
  {
    data: {
      question: "How do I create a new project?",
      context: "To create a new project, go to the Dashboard and click 'New Project'.",
    },
  },
  {
    data: {
      question: "Can I use this with Kubernetes?",
      context: "We support Docker containers and serverless functions.",
    },
    assertions: [
      "The response does NOT claim Kubernetes is supported",
      "The response acknowledges that the information is not available",
    ],
    executionPolicy: { runsPerItem: 3, passThreshold: 2 },
  },
]);

import { runTests } from "opik";
import OpenAI from "openai";

const openai = new OpenAI();

function makeTask(systemPrompt: string) {
  return async (item: Record<string, unknown>) => {
    const response = await openai.chat.completions.create({
      model: "gpt-4o-mini",
      messages: [
        { role: "system", content: systemPrompt },
        { role: "user", content: `Question: ${item.question}\n\nContext:\n${item.context}` },
      ],
    });
    return { input: item, output: response.choices[0]!.message.content };
  };
}

const PROMPT_V1 = "You are a helpful assistant. Be as detailed as possible.";
const PROMPT_V2 = "You are a concise assistant. Answer based ONLY on the provided context.";

const resultV1 = await runTests({ testSuite: suite, task: makeTask(PROMPT_V1) });
const resultV2 = await runTests({ testSuite: suite, task: makeTask(PROMPT_V2) });

console.log(`v1 pass rate: ${((resultV1.passRate ?? 0) * 100).toFixed(0)}%`);
console.log(`v2 pass rate: ${((resultV2.passRate ?? 0) * 100).toFixed(0)}%`);

await client.flush();

// Dataset creation --------------------------------------------------------

// Define dataset item type
type DatasetItem = {
    input: string;
    expected: string;
};
const llmTask: EvaluationTask<DatasetItem> = async (datasetItem) => {
    const { input } = datasetItem;
    const openai = new OpenAI();
    const response = await openai.chat.completions.create({
        model: "gpt-4o",
        messages: [
            { role: "system", content: "You are a coding assistant" },
            { role: "user", content: input }
        ],
    });
    return { output: response.choices[0]!.message.content };
};

// Get or create the dataset - items are automatically deduplicated
// const client = new Opik();
const dataset = await client.getOrCreateDataset<DatasetItem>("Example dataset", "Evaluation dataset", "my-project");
await dataset.insert([
    {
        input: "Hello, world!",
        expected: "Hello, world!"
    },
    {
        input: "What is the capital of France?",
        expected: "Paris"
    },
]);
// Define the metric
const exact_match_metric = new ExactMatch();
// Run the evaluation
const result = await evaluate({
    dataset,
    task: llmTask,
    scoringMetrics: [exact_match_metric],
    experimentName: "Example Evaluation",
    projectName: "niche_newsletter",
});
console.log(`Experiment ID: ${result.experimentId}`);
console.log(`Experiment Name: ${result.experimentName}`);
console.log(`Total test cases: ${result.testResults.length}`);