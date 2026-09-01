from langgraph.types import Command
from langchain_core.messages import ToolMessage, HumanMessage
from langchain.tools import tool, ToolRuntime
from langchain_openrouter import ChatOpenRouter

import wave, io, os, base64, time, httpx, json
from dotenv import load_dotenv
from typing import List, Optional, Literal
from openrouter import OpenRouter, utils
import fal_client
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field

from ...utils import FileEditingTools, SkillLoadingTools
from .state import ContentCreatorState
from .....models import IMAGE_GEN_MODEL, VIDEO_GEN_MODEL, LIPSYNC_MODEL, MEMORY_MANAGEMENT_MODEL

load_dotenv()

class CharacterFeatures(BaseModel):
    consistency_anchors: List[str] = Field(
        description="The fixed features that MUST appear identically in every generated asset (e.g. exact hair color hex, skin tone hex, eye color, distinguishing marks, build) — the highest-priority details for image/video prompt consistency."
    )
    face_features: List[str] = Field(
        description="Condensed, prompt-ready face descriptors: shape, skin tone/texture, eye color and shape, brows, nose, mouth, cheekbones/jawline, chin — as short visual phrases usable directly in a generation prompt."
    )
    hair: List[str] = Field(
        description="Hair color (hex), texture, length, default style, and the allowed variation range (e.g. ponytail, braid) usable in a generation prompt."
    )
    body: List[str] = Field(
        description="Height, build/frame, proportions, muscle tone, posture, and body skin tone — condensed to prompt-ready visual phrases."
    )
    signature_outfits: List[str] = Field(
        description="Named signature looks with their exact garments, colors (hex where given), and styling details, ready to drop into an image/video prompt (e.g. 'Training Day: high-waisted black leggings, fitted white cropped tank...')."
    )
    accessories_and_makeup: List[str] = Field(
        default_factory=list,
        description="Fixed/recurring accessories (rings, jewelry, footwear) and default makeup style, as prompt-ready phrases."
    )
    negative_constraints: List[str] = Field(
        description="Things that must never appear in generated visuals (e.g. no tattoos, no freckles, no heavy makeup) — usable as negative-prompt guidance."
    )

class AgentTools:

    @tool
    def generate_image(prompt: str, filename: str, runtime: ToolRuntime[None, ContentCreatorState]) -> Command:
        "Generate an image from a text prompt via OpenRouter and save it as '{filename}.jpg' under the influencer's social_contents/images folder. Returns the image for you to inspect and stores its hosted URL in state as img_url."
        full_output_path = f"src/influencers/{runtime.state.get("influencer_name")}/social_contents/images"
        os.makedirs(full_output_path, exist_ok=True)
        today = datetime.now().strftime("%Y%m%d_%H%M%S")
        with OpenRouter(api_key=os.getenv("OPENROUTER_API_KEY", "")) as open_router:
            res = open_router.images.generate(
                model=IMAGE_GEN_MODEL,
                prompt=prompt,
                n=1,
                aspect_ratio="1:1",
                output_format="jpeg",
                timeout_ms=90000,
                retries=utils.RetryConfig("backoff", utils.BackoffStrategy(500, 5000, 1.5, 30000), False),
            )
            b64_json = res.data[0].b64_json
            image_bytes = base64.b64decode(b64_json)
            with open(f"{full_output_path}/{today}_{filename}.jpg", "wb") as f:
                f.write(image_bytes)

        img_url = fal_client.upload_file(f"{full_output_path}/{today}_{filename}.jpg")

        return Command(
            update={
                "messages":[
                    ToolMessage(content= "Image has been successfully generated and saved", tool_call_id=runtime.tool_call_id),
                    HumanMessage(content=[
                        {"type": "text", "text": f"The generated image ({full_output_path}) is the following:"},
                        {
                            "type": "image",
                            "url": img_url,
                            "mime_type": "jpeg",
                        },
                    ]),
                ],
                "img_url": img_url,
            }
        )

    @tool
    def edit_image(prompt: str, filename: str, runtime: ToolRuntime[None, ContentCreatorState]) -> Command:
        "Edit an image per the given prompt, grounded against the influencer's most recently generated images (or, if none exist yet, her locked reference photos), and save the result as '{filename}.jpg' under the influencer's social_contents/images folder. Reference images are fetched automatically — no other tool call needed first. Returns the edited image for you to inspect and updates its hosted URL in state as img_url."
        influencer_name = runtime.state.get("influencer_name")
        prev_images_folder = f"src/influencers/{influencer_name}/social_contents/images"
        image_urls = []
        if Path(prev_images_folder).exists():
            # Retrieve the last three images for the agent
            history_files = sorted(Path(prev_images_folder).glob("*.jpg"))[-3:]
            [image_urls.append(fal_client.upload_file(file)) for file in history_files]

        sample_images_folder = f"src/influencers/{influencer_name}/img"
        history_files = sorted(Path(sample_images_folder).glob("*.jpg"))[:3]
        [image_urls.append(fal_client.upload_file(file)) for file in history_files]

        today = datetime.now().strftime("%Y%m%d_%H%M%S")

        result = fal_client.submit(
            "meta/muse-image/edit",
            arguments={
                "prompt": prompt,
                "image_urls": image_urls,
                "num_images": 1,
            },
        ).get()

        edited_url = result["images"][0]["url"]
        image_bytes = httpx.get(edited_url).content
        with open(f"{prev_images_folder}/{today}_{filename}.jpg", "wb") as f:
            f.write(image_bytes)

        return Command(update={
            "messages":[
                ToolMessage(content= "Image has been successfully edited and saved", tool_call_id=runtime.tool_call_id),
                HumanMessage(content=[
                    {"type": "text", "text": f"The generated image ({prev_images_folder}) is the following:"},
                    {
                        "type": "image",
                        "url": edited_url,
                        "mime_type": "jpeg",
                    },
                ]),
            ],
            "img_url": [edited_url]
        })

    @tool
    def generate_video(prompt: str, filename: str, duration: int, runtime: ToolRuntime[None, ContentCreatorState], from_image: bool = False) -> Command:
        "Generate a short video from a text prompt via OpenRouter and save it as '{filename}.mp4' under the influencer's social_contents/videos folder. Set from_image=True to animate the most recently generated image (img_url in state) as the video's first frame instead of generating from text alone. duration is in seconds and capped at 10. Returns the video for you to inspect and stores its hosted URL in state as video_url."
        assert duration <= 10, "Duration must be max 10 seconds long"
        full_output_path = f"src/influencers/{runtime.state.get("influencer_name")}/social_contents/videos"
        os.makedirs(full_output_path, exist_ok=True)
        retries = utils.RetryConfig("backoff", utils.BackoffStrategy(500, 5000, 1.5, 30000), False)
        today = datetime.now().strftime("%Y%m%d_%H%M%S")

        with OpenRouter(api_key=os.getenv("OPENROUTER_API_KEY", "")) as open_router:
            job = open_router.video_generation.generate(
                model=VIDEO_GEN_MODEL,
                prompt=prompt,
                aspect_ratio="9:16",
                resolution="720p",
                frame_images=[{
                    "image_url": {"url": runtime.state.get("img_url")[-1]},
                    "type": "image_url",
                    "frame_type": "first_frame",
                }] if from_image else None,
                duration=duration,
                timeout_ms=60000,
                retries=retries,
                generate_audio=False
            )

            poll_interval_s = 10
            max_attempts = 30  # ~5 minutes of polling before giving up
            for _ in range(max_attempts):
                if job.status in ("completed", "failed", "cancelled", "expired"):
                    break
                time.sleep(poll_interval_s)
                job = open_router.video_generation.get_generation(job_id=job.id, timeout_ms=30000, retries=retries)

            if job.status != "completed":
                raise RuntimeError(f"Video generation for '{filename}' did not complete (status: {job.status}, error: {job.error})")

            video_res = open_router.video_generation.get_video_content(job_id=job.id, timeout_ms=60000, retries=retries)
            video_res.read()
            video_bytes = video_res.content

            with open(f"{full_output_path}/{today}_{filename}.mp4", "wb") as f:
                f.write(video_bytes)

        video_url = fal_client.upload_file(f"{full_output_path}/{today}_{filename}.mp4")

        return Command(
            update={
                "messages": [
                    ToolMessage(content=f"Video has been successfully generated and saved to {full_output_path}/{filename}.mp4", tool_call_id=runtime.tool_call_id),
                    HumanMessage(content=[
                        {"type": "text", "text": f"The generated video ({full_output_path}) is the following:"},
                        {
                            "type": "video",
                            "url": video_url,
                            "mime_type": "video/mp4",
                        },
                    ]),
                ],
                "video_url": video_url
            }
        )

    @tool
    def generate_audio(speech_input: str, filename: str, runtime: ToolRuntime[None, ContentCreatorState]) -> Command:
        "Generate a speech clip for the given text using the influencer's selected voice (voice_name in state) via Gemini TTS, and save it as '{filename}.wav' under the influencer's social_contents/audio folder. Returns the audio for you to listen to and stores its hosted URL and duration in state as audio_url and audio_duration."
        full_output_path = f"src/influencers/{runtime.state.get("influencer_name")}/social_contents/audio"
        os.makedirs(full_output_path, exist_ok=True)
        today = datetime.now().strftime("%Y%m%d_%H%M%S")
        with OpenRouter(
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
        ) as open_router:

            res = open_router.tts.create_speech(input=speech_input, model="google/gemini-3.1-flash-tts-preview", response_format="pcm", speed=1, voice=runtime.state.get("voice_name"))
            res.read()

            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(24000)
                wav_file.writeframes(res.content)
            wav_bytes = wav_buffer.getvalue()
            audio_duration = len(res.content) / 2 / 24000  # 16-bit mono samples @ 24kHz

            with open(f"{full_output_path}/{today}_{filename}.wav", "wb") as f:
                f.write(wav_bytes)

            audio_b64 = base64.b64encode(wav_bytes).decode("utf-8")

        audio_url = fal_client.upload_file(f"{full_output_path}/{today}_{filename}.wav")

        return Command(
            update={
                "messages":[
                    ToolMessage(content=f"Speech has been successfully generated and saved (duration: {audio_duration:.2f}s)", tool_call_id=runtime.tool_call_id),
                    HumanMessage(content=[
                        {"type": "text", "text": f"The generated speech ({full_output_path}) is the following:"},
                        {
                            "type": "audio",
                            "url": audio_url,
                            "mime_type": "wav",
                        },
                    ]),
                ],
                "audio_url": audio_url,
                "audio_duration": audio_duration
            }
        )

    @tool
    def lipsync_video_wth_audio(filename: str, runtime: ToolRuntime[None, ContentCreatorState]) -> Command:
        "Lip-sync the most recently generated video (video_url in state) to the most recently generated audio (audio_url in state) and save the result as '{filename}.mp4' under the influencer's social_contents/lipsynced folder. Returns the synced video for you to inspect and stores its URL in state as lipsynced."
        full_output_path = f"src/influencers/{runtime.state.get("influencer_name")}/social_contents/lipsynced"
        os.makedirs(full_output_path, exist_ok=True)
        result = fal_client.submit(
            LIPSYNC_MODEL,
            arguments={
                "video_url": runtime.state.get("video_url"),
                "audio_url": runtime.state.get("audio_url"),
            },
        ).get()
        return Command(
            update={
                "messages": [
                    ToolMessage(content=f"Lipsync has been successfully and saved to {full_output_path}/{filename}.mp4", tool_call_id=runtime.tool_call_id),
                    HumanMessage(content=[
                        {"type": "text", "text": f"The generated video ({full_output_path}) is the following:"},
                        {
                            "type": "video",
                            "url": result["video"]["url"],
                            "mime_type": "video/mp4",
                        },
                    ]),
                ],
                "lipsynced": result["video"]["url"]
            }
        )

    @tool
    def read_captions(runtime: ToolRuntime[None, ContentCreatorState]) -> str:
        "Read the influencer's CAPTION.md file content"
        influencer_name = runtime.state.get("influencer_name")
        influencer_folder = f"src/influencers/{influencer_name}/social_contents"
        os.makedirs(influencer_folder, exist_ok=True)
        try:
            return FileEditingTools.read_file(f"{influencer_folder}/CAPTION.md")
        except:
            with open(f"{influencer_folder}/CAPTION.md", "w") as f:
                f.write("")
            return FileEditingTools.read_file(f"{influencer_folder}/CAPTION.md")

    @tool
    def append_content(content: str, runtime: ToolRuntime[None, ContentCreatorState]) -> str:
        "Append new content to the end of the influencer's CAPTION.md file"
        influencer_name = runtime.state.get("influencer_name")
        influencer_folder = f"src/influencers/{influencer_name}/social_contents"
        return FileEditingTools.append_filecontent(content, filepath=f"{influencer_folder}/CAPTION.md")

    @tool
    def edit_captions(to_replace: str, replace_with: str, runtime: ToolRuntime[None, ContentCreatorState]) -> str:
        "Replace an exact snippet of text in the influencer's CAPTION.md file with new text"
        influencer_name = runtime.state.get("influencer_name")
        influencer_folder = f"src/influencers/{influencer_name}/social_contents"
        return FileEditingTools.edit_filecontent(to_replace, replace_with, filepath=f"{influencer_folder}/CAPTION.md")

    @tool
    def read_persona_info(identity: Literal["CHARACTER", "PERSONALITY", "BACKSTORY"], runtime: ToolRuntime[None, ContentCreatorState]) -> str:
        "Read the influencer's PERSONALITY.md, BACKSTORY.md or CHARACTER.md file content"
        influencer_name = runtime.state.get("influencer_name")

        stored_persona_info = runtime.store.get(("content_production", influencer_name), identity.lower())
        if stored_persona_info:
            return json.dumps(stored_persona_info.value)

        persona_path = f"src/influencers/{influencer_name}/{identity}.md"

        with open(persona_path, "r", encoding="utf-8") as f:
            persona = f.read()

        # Extract the key aspects from it and save it for long term
        extracter_model = ChatOpenRouter(model=MEMORY_MANAGEMENT_MODEL, temperature=.2)
        extraction_prompt = f"Based on the provided schema, fill in the sections with the information about this influencer. Fill in those that you found information about:\n\n {persona}"

        result = extracter_model.with_structured_output(schema=CharacterFeatures, method="json_schema").invoke(extraction_prompt)
        runtime.store.put(
            ("content_production", influencer_name,),
            identity.lower(),
            result.model_dump(),
        )

        return persona

    @tool
    def load_available_skills() -> List[dict] | str:
        "List the names and descriptions of the personality skills available to load"
        return SkillLoadingTools.load_skill_names(r"src\agents\content_production\specialists\sm_writer_agent\skills")

    @tool
    def load_skill_content(skill_name: str) -> str:
        "Load the full content of a specific personality skill by name"
        return SkillLoadingTools.load_skill(skill_name, r"src\agents\content_production\specialists\sm_writer_agent\skills")

    