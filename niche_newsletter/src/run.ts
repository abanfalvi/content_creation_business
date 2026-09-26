import { researchAgent } from "./signal-editor-dep/research_agent/agent.js";
import { relFilterAgent } from "./signal-editor-dep/rel_filter_agent/agent.js";
import { editorAgent } from "./signal-editor-dep/editor_agent/agent.js";
import { SMAgent } from "./distribution-dep/sm_agent/agent.js";
import { OutreachAgent } from "./distribution-dep/user_outreach_agent/agent.js";
import {MODELS, opikHandler} from "./models.js";
import {HumanMessage} from "@langchain/core/messages";
import { ChatOpenRouter } from "@langchain/openrouter";
import { OpenRouter } from "@openrouter/sdk";
import type { ImageGenerationRequestAspectRatio } from "@openrouter/sdk/models";
import {z} from "zod";
import { writeFile } from 'fs/promises';
import dotenv from 'dotenv';

dotenv.config();

const promptSchema = z.object({
    prompt: z.string().describe("The refined image-generation prompt"),
    negative_prompt: z.string().describe("Prompt what to avoid when generating the image"),
});

const instruction = "Write an image generation prompt for generating the logo for my newsletter business, be specific on how the logo should look like. I want a logo (no need for text in the picture, only some shapes) that truly represents a newsletter business can be used for branding: it shares content on AI news/latest developments and on techniques to help people upskill themselves in AI. \n Return your answer in the provided schema.";

async function runAgent(instruction:string) {
    
    try {
        const result = await OutreachAgent.invoke(
            {
                messages: [new HumanMessage(instruction)],
                // researchTopic: "ai_marketing_automation"
            },
            { callbacks: [opikHandler], recursionLimit: 30 }
        );
        console.log(result.messages.at(-1)?.content);
    } catch (error) {
        console.log(error)
    }
};

const promptEngineer = new ChatOpenRouter({model: "openai/gpt-6-luna", maxTokens: 2048, maxRetries: 2}).withStructuredOutput(promptSchema, {method: "functionCalling"});
const openRouter = new OpenRouter({ apiKey: process.env.OPENROUTER_API_KEY });

async function imageGenerator(direction: string, fileName: string) {
    const result = await promptEngineer.invoke(direction);
    let genResult;
    try {
        genResult = await openRouter.images.generate({
            imageGenerationRequest: {
                model: "inclusionai/ming-image-0.1-design",
                prompt: `${result.prompt}\n\nNegative prompt: ${result.negative_prompt}`,
                n: 1,
                /// aspectRatio: "1:1",
                outputFormat: "png",
            },
        });
    } catch (error) {
        return `Image generation failed: ${error}`;
    }

    if (genResult instanceof ReadableStream) {
        return "Image generation unexpectedly returned a streaming response.";
    }

    const image = genResult.data[0];
    if (!image?.b64Json) {
        return "Image generation returned no image data.";
    }
    const imageBytes = Buffer.from(image.b64Json, "base64");
    await writeFile(`assets/${fileName}.png`, imageBytes)
    return "Image has been generated"
}
console.log(await imageGenerator(instruction, "logo"))

// await opikHandler.flushAsync();