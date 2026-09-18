import { YoutubeTranscript } from "youtube-transcript";
import { join } from 'path';
import { mkdir, writeFile } from "fs/promises";

async function getCaption(videoIdOrUrl: string, videoTitle: string) {
    try {
        const transcript = await YoutubeTranscript.fetchTranscript(videoIdOrUrl);
        console.log(`Fetched ${transcript.length} segments.`);
    
        const videoId = videoTitle.toLowerCase().replace(" ", "_");
        const outDir = "src/signal-editor-dep/use_case_writer_agent/scratch_pad/";
        const outPath = join(outDir, `${videoId}_transcript.md`);
    
        const fullText = transcript.map((seg) => seg.text).join(" ");
        const markdown = `# Transcript: ${videoId}\n\nSource: ${videoIdOrUrl}\n\n${fullText}\n`;
        await writeFile(outPath, markdown, "utf-8");
    
        return `Saved transcript (${fullText.length} chars) to ${outPath}`
    } catch (error) {
        return `Failed to fetch transcript: ${error}`
    }
};

console.log(await getCaption("https://www.youtube.com/watch?v=XoGvCBRnwLs", "llm_distributed_training"))