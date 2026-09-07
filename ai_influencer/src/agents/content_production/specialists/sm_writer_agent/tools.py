from langgraph.types import Command
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langchain_core.messages import ToolMessage, HumanMessage, AIMessage, RemoveMessage
from langchain_core.messages.utils import get_buffer_string
from langchain.tools import tool, ToolRuntime
from langchain_openrouter import ChatOpenRouter

import wave, io, os, base64, time, httpx, json, re
from dotenv import load_dotenv
from typing import List, Optional, Literal
from openrouter import OpenRouter, utils
import fal_client
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field

from ...utils import FileEditingTools, SkillLoadingTools
from .state import ContentCreatorState
from .....models import IMAGE_GEN_MODEL, VIDEO_GEN_MODEL, LIPSYNC_MODEL, MEMORY_MANAGEMENT_MODEL, PERSONA_FALLBACK_MODEL_1, PERSONA_FALLBACK_MODEL_2

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

class EditContentCalendar(BaseModel):
    pass

_KEEP_RECENT_MESSAGES = 12
"""How many of the most recent messages `compress_context` always leaves untouched."""

_MIN_HISTORY_TO_COMPRESS = 6
"""Below this many older messages, compression isn't worth the summarization call."""

_compression_model = ChatOpenRouter(model="inclusionai/ling-3.0-flash", temperature=0.2)

_COMPRESSION_PROMPT = """You are compressing the working conversation history of a social-media content writer agent, so it can keep going without losing track of what's already been decided or produced.

Read the conversation below and extract only what's needed to continue the work coherently. Structure your output with these sections, writing "None" where a section has nothing to report:

## POST BRIEF & INTENT
What post is being created and for whom (goal, angle, format).

## PERSONA DETAILS ESTABLISHED
Any persona-specific facts, traits, or phrasing already looked up or decided (from CHARACTER.md / PERSONALITY.md / BACKSTORY.md) that must not be re-derived or contradicted.

## MEDIA GENERATED SO FAR
Every image/video/audio asset created or edited: filename, what it shows, and whether it's been accepted or needs rework.

## CAPTION STATUS
The current caption draft or what's been recorded to CAPTION.md, if any.

## GUARDRAIL FEEDBACK
Any specific issue a guardrail (safety, consistency) flagged that still needs addressing, quoted or closely paraphrased.

## NEXT STEPS
What remains to finish this post.

Respond ONLY with the filled-in sections above — no preamble, no text before or after.

Conversation to compress:
{messages}"""


def _find_safe_cutoff_point(messages: list, cutoff_index: int) -> int:
    "Nudge a cutoff index so it never splits an AIMessage's tool_calls from their ToolMessage replies."
    if cutoff_index >= len(messages) or not isinstance(messages[cutoff_index], ToolMessage):
        return cutoff_index

    tool_call_ids = set()
    idx = cutoff_index
    while idx < len(messages) and isinstance(messages[idx], ToolMessage):
        if messages[idx].tool_call_id:
            tool_call_ids.add(messages[idx].tool_call_id)
        idx += 1

    for i in range(cutoff_index - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, AIMessage) and msg.tool_calls:
            ai_call_ids = {tc.get("id") for tc in msg.tool_calls if tc.get("id")}
            if tool_call_ids & ai_call_ids:
                return i

    return idx


def _find_safe_cutoff(messages: list, keep: int) -> int:
    if len(messages) <= keep:
        return 0
    return _find_safe_cutoff_point(messages, len(messages) - keep)


def _summarize_messages(messages_to_summarize: list) -> str:
    formatted = get_buffer_string(messages_to_summarize)
    response = _compression_model.invoke(_COMPRESSION_PROMPT.format(messages=formatted))
    return response.content if isinstance(response.content, str) else str(response.content)

def update_calendar(influencer_name: str, aim: Literal["append", "edit"], content_id: str, to_replace: str = "", replace_with: str = "", caption_text: str = "", is_caption: bool = True, url: str = "") -> None:
    with open(f"src/influencers/{influencer_name}/CALENDAR.json", "r", encoding="utf-8") as f:
        calendar = json.loads(f.read())
    entry = [post for _, e in calendar.items() for post in e if post["id"] == content_id]
    if is_caption:
        if aim == "edit":
            entry[0]['caption'] = entry[0]['caption'].replace(to_replace, replace_with)
        else:
            entry[0]['caption'] = caption_text
    else:
        entry[0]['asset_links'].append(url)

    with open(f"src/influencers/{influencer_name}/CALENDAR.json", "w", encoding="utf-8") as f:
        json.dump(calendar, f, indent=2)

    return None


class AgentTools:

    @tool
    def generate_image(prompt: str, filename: str, runtime: ToolRuntime[None, ContentCreatorState]) -> Command:
        "Generate an image from a text prompt via OpenRouter and save it as '{filename}.jpg' under the influencer's social_contents/images folder. content_id is the CALENDAR.json entry this asset belongs to — its hosted URL is recorded there automatically. Returns the image for you to inspect and stores its hosted URL in state as img_url."
        influencer_name = runtime.state.get("influencer_name")
        full_output_path = f"src/influencers/{influencer_name}/social_contents/images"
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

        update_calendar(influencer_name, "append", runtime.state.get("content_id"), is_caption=False, url=img_url)

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
                "img_url": [img_url],
            }
        )

    @tool
    def edit_image(prompt: str, filename: str, runtime: ToolRuntime[None, ContentCreatorState]) -> Command:
        "Edit an image per the given prompt, grounded against the influencer's most recently generated images (or, if none exist yet, her locked reference photos), and save the result as '{filename}.jpg' under the influencer's social_contents/images folder. Reference images are fetched automatically — no other tool call needed first. content_id is the CALENDAR.json entry this asset belongs to — its hosted URL is recorded there automatically. Returns the edited image for you to inspect and updates its hosted URL in state as img_url."
        influencer_name = runtime.state.get("influencer_name")
        prev_images_folder = f"src/influencers/{influencer_name}/social_contents/images"
        image_urls = []
        os.makedirs(prev_images_folder, exist_ok=True)
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

        update_calendar(influencer_name, "append", runtime.state.get("content_id"), is_caption=False, url=edited_url)

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
        "Generate a short video from a text prompt via OpenRouter and save it as '{filename}.mp4' under the influencer's social_contents/videos folder. Set from_image=True to animate the most recently generated image (img_url in state) as the video's first frame instead of generating from text alone. duration is in seconds and capped at 10. content_id is the CALENDAR.json entry this asset belongs to — its hosted URL is recorded there automatically. Returns the video for you to inspect and stores its hosted URL in state as video_url."
        assert duration <= 10, "Duration must be max 10 seconds long"
        influencer_name = runtime.state.get("influencer_name")
        full_output_path = f"src/influencers/{influencer_name}/social_contents/videos"
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

        update_calendar(influencer_name, "append", runtime.state.get("content_id"), is_caption=False, url=video_url)

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
        "Generate a speech clip for the given text using the influencer's selected voice (voice_name in state) via Gemini TTS, and save it as '{filename}.wav' under the influencer's social_contents/audio folder. content_id is the CALENDAR.json entry this asset belongs to — its hosted URL is recorded there automatically. Returns the audio for you to listen to and stores its hosted URL and duration in state as audio_url and audio_duration."
        influencer_name = runtime.state.get("influencer_name")
        full_output_path = f"src/influencers/{influencer_name}/social_contents/audio"
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

            # audio_b64 = base64.b64encode(wav_bytes).decode("utf-8")

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
        "Lip-sync the most recently generated video (video_url in state) to the most recently generated audio (audio_url in state) and save the result as '{filename}.mp4' under the influencer's social_contents/lipsynced folder. content_id is the CALENDAR.json entry this asset belongs to — its hosted URL is recorded there automatically. Returns the synced video for you to inspect and stores its URL in state as lipsynced."
        influencer_name = runtime.state.get("influencer_name")
        full_output_path = f"src/influencers/{influencer_name}/social_contents/lipsynced"
        os.makedirs(full_output_path, exist_ok=True)
        result = fal_client.submit(
            LIPSYNC_MODEL,
            arguments={
                "video_url": runtime.state.get("video_url"),
                "audio_url": runtime.state.get("audio_url"),
            },
        ).get()

        lipsynced_url = result["video"]["url"]
        update_calendar(influencer_name, "append", runtime.state.get("content_id"), is_caption=False, url=lipsynced_url)

        return Command(
            update={
                "messages": [
                    ToolMessage(content=f"Lipsync has been successfully and saved to {full_output_path}/{filename}.mp4", tool_call_id=runtime.tool_call_id),
                    HumanMessage(content=[
                        {"type": "text", "text": f"The generated video ({full_output_path}) is the following:"},
                        {
                            "type": "video",
                            "url": lipsynced_url,
                            "mime_type": "video/mp4",
                        },
                    ]),
                ],
                "lipsynced": lipsynced_url
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
        "Append new content to the end of the influencer's CAPTION.md file."
        influencer_name = runtime.state.get("influencer_name")
        influencer_folder = f"src/influencers/{influencer_name}/social_contents"
        update_calendar(
            influencer_name,
            "append",
            runtime.state.get("content_id"),
            caption_text=content
        )
        return FileEditingTools.append_filecontent(content, filepath=f"{influencer_folder}/CAPTION.md")

    @tool
    def edit_captions(to_replace: str, replace_with: str, runtime: ToolRuntime[None, ContentCreatorState]) -> str:
        "Replace an exact snippet of text in the influencer's CAPTION.md file with new text"
        influencer_name = runtime.state.get("influencer_name")
        influencer_folder = f"src/influencers/{influencer_name}/social_contents"
        update_calendar(
            influencer_name,
            "edit",
            runtime.state.get("content_id"),
            to_replace,
            replace_with
        )
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

        structured_extracter_model = extracter_model.with_structured_output(schema=CharacterFeatures, method="json_schema").with_fallbacks([
            ChatOpenRouter(model=PERSONA_FALLBACK_MODEL_1, temperature=.2).with_structured_output(schema=CharacterFeatures, method="json_schema"),
            ChatOpenRouter(model=PERSONA_FALLBACK_MODEL_2, temperature=.2).with_structured_output(schema=CharacterFeatures, method="json_schema"),
        ])
        result = structured_extracter_model.invoke(extraction_prompt)
        runtime.store.put(
            ("content_production", influencer_name,),
            identity.lower(),
            result.model_dump(),
        )

        return persona

    @tool
    def compress_context(runtime: ToolRuntime[None, ContentCreatorState]) -> Command:
        "Compress your own conversation history when it's grown overwhelming: too many piled-up generated images/videos/audio, several rounds of guardrail back-and-forth, or you're struggling to find the relevant detail buried earlier in the thread. Condenses everything older into a structured summary (post brief, persona details already established, media generated, caption status, open guardrail feedback, next steps) and keeps only the most recent messages intact. Call it yourself, on your own judgment — there's no fixed schedule for it. Takes no arguments."
        messages = list(runtime.state.get("messages", []))

        if len(messages) < 2:
            return Command(update={"messages": [ToolMessage(content="Conversation is too short to compress.", tool_call_id=runtime.tool_call_id)]})

        current_call, history = messages[-1], messages[:-1]

        if len(history) < _MIN_HISTORY_TO_COMPRESS:
            return Command(update={"messages": [ToolMessage(content="Not enough conversation history yet to make compression worthwhile.", tool_call_id=runtime.tool_call_id)]})

        cutoff_index = _find_safe_cutoff(history, _KEEP_RECENT_MESSAGES)
        to_summarize, preserved = history[:cutoff_index], history[cutoff_index:]

        if not to_summarize:
            return Command(update={"messages": [ToolMessage(content="Nothing old enough to compress yet — recent history is already within the retained window.", tool_call_id=runtime.tool_call_id)]})

        summary = _summarize_messages(to_summarize)
        summary_message = HumanMessage(
            content=f"Here is a summary of the conversation so far, replacing the earlier messages that were compressed:\n\n{summary}",
            additional_kwargs={"lc_source": "summarization"},
        )

        return Command(update={
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                summary_message,
                *preserved,
                current_call,
                ToolMessage(
                    content=f"Context compressed: {len(to_summarize)} older message(s) condensed into the summary above; {len(preserved)} recent message(s) kept intact.",
                    tool_call_id=runtime.tool_call_id,
                ),
            ]
        })

    @tool
    def load_available_skills() -> List[dict] | str:
        "List the names and descriptions of the personality skills available to load"
        return SkillLoadingTools.load_skill_names(r"src\agents\content_production\specialists\sm_writer_agent\skills")

    @tool
    def load_skill_content(skill_name: str) -> str:
        "Load the full content of a specific personality skill by name"
        return SkillLoadingTools.load_skill(skill_name, r"src\agents\content_production\specialists\sm_writer_agent\skills")

    