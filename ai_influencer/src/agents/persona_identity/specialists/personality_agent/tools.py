from langgraph.types import Command
from langchain_core.messages import ToolMessage, HumanMessage
from langchain.tools import tool, ToolRuntime

from langchain_core.documents import Document
import json, frontmatter, os, base64, wave, io
from dotenv import load_dotenv
from typing import Optional, Literal
from openrouter import OpenRouter

from ...utils import FileEditingTools, check_previous_influencers_persona
from .state import PersonalityState

load_dotenv()

VOICE_NAMES = Literal[
    "Achernar",
    "Aoede",
    "Autonoe",
    "Callirrhoe",
    "Despina",
    "Erinome",
    "Gacrux",
    "Kore",
    "Laomedeia",
    "Leda",
    "Pulcherrima",
    "Sulafat",
    "Vindemiatrix",
    "Zephyr",
]

class AgentTools:

    @tool
    def read_influencer_personality(runtime: ToolRuntime[None, PersonalityState]) -> str:
        "Read the influencer's PERSONALITY.md file content"
        influencer_name = runtime.state.get("influencer_name")
        influencer_folder = f"src/influencers/{influencer_name}"
        if influencer_name:
            return FileEditingTools.read_file(f"src/influencers/{influencer_name}/PERSONALITY.md")
        else:
            with open(f"{influencer_folder}/PERSONALITY.md", "w") as f:
                f.write("")
            return FileEditingTools.read_file(f"src/influencers/{influencer_name}/PERSONALITY.md")

    @tool
    def append_content(content: str, runtime: ToolRuntime[None, PersonalityState]) -> str:
        "Append new content to the end of the influencer's PERSONALITY.md file"
        influencer_name = runtime.state.get("influencer_name")
        return FileEditingTools.append_filecontent(content, filepath=f"src/influencers/{influencer_name}/PERSONALITY.md")

    @tool
    def edit_influencer_personality(to_replace: str, replace_with: str, runtime: ToolRuntime[None, PersonalityState]) -> str:
        "Replace an exact snippet of text in the influencer's PERSONALITY.md file with new text"
        influencer_name = runtime.state.get("influencer_name")
        return FileEditingTools.edit_filecontent(to_replace, replace_with, filepath=f"src/influencers/{influencer_name}/PERSONALITY.md")

    @tool
    def check_existing_influencers(runtime: ToolRuntime[None, PersonalityState]) -> str:
        "Check the already-designed character/personality/backstory summaries of every other existing influencer, so this one's values, traits, and communication style aren't too similar to any of them. Call before finalizing Core Values, Personality Traits, and Consistency Anchors."
        influencer_name = runtime.state.get("influencer_name")
        return check_previous_influencers_persona(influencer_name, runtime.store)

    @staticmethod
    def _generate_voice_sample(voice_name: str) -> tuple[str, str]:
        "Generate (or reuse a cached) sample voice clip via Gemini TTS. Returns (output_path, base64_audio)."
        speech_input = f"This is a sample audio from {voice_name}. I can happily be your next AI influencer. How do I sound?"
        output_path = f"assets/voice_samples/{voice_name}.wav"
        if os.path.exists(output_path):
            with open(output_path, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode("utf-8")
            return output_path, audio_b64

        with OpenRouter(
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
        ) as open_router:

            res = open_router.tts.create_speech(input=speech_input, model="google/gemini-3.1-flash-tts-preview", response_format="pcm", speed=1, voice=voice_name)
            res.read()

            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(24000)
                wav_file.writeframes(res.content)
            wav_bytes = wav_buffer.getvalue()

            with open(output_path, "wb") as f:
                f.write(wav_bytes)

            audio_b64 = base64.b64encode(wav_bytes).decode("utf-8")

        return output_path, audio_b64

    @tool
    def preview_voice(voice_name: VOICE_NAMES, runtime: ToolRuntime[None, PersonalityState]) -> Command:
        "Generate (or reuse a cached) sample voice clip for the given voice name via Gemini TTS and return the audio for you to listen. This only lets you audition a candidate — it does NOT commit to it. Call select_influencer_voice exactly once, after you've decided, to actually set the voice."
        output_path, audio_b64 = AgentTools._generate_voice_sample(voice_name)

        return Command(update={
            "messages": [
                ToolMessage(content="Audio loaded — see the attached clip below.", tool_call_id=runtime.tool_call_id),
                HumanMessage(content=[
                    {"type": "text", "text": f"The voice sample for {voice_name} ({output_path}) is the following:"},
                    {
                        "type": "audio",
                        "base64": audio_b64,
                        "mime_type": "audio/wav",
                    },
                ]),
            ],
        })

    @tool
    def select_influencer_voice(voice_name: VOICE_NAMES, runtime: ToolRuntime[None, PersonalityState]) -> Command:
        "Commit to the final voice for this influencer, after auditioning candidates with preview_voice. Call this exactly once, after you've decided."
        return Command(update={
            "messages": [
                ToolMessage(content=f"Voice committed: {voice_name}.", tool_call_id=runtime.tool_call_id),
            ],
            "voice_name": voice_name
        })