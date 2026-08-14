from openrouter import OpenRouter
from dotenv import load_dotenv
import os
import base64
from typing import Literal
from langchain.tools import tool, ToolRuntime
from langgraph.types import Command

from langchain_core.messages import HumanMessage, ToolMessage

from pydub import AudioSegment
from pydub.silence import detect_silence, split_on_silence
from pydub.effects import normalize as pydub_normalize


load_dotenv()

class VoiceAgentsTools:

    @staticmethod
    def generate_audio(speech_input: str, voice: str, output_path: str) -> str:
        with OpenRouter(
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
        ) as open_router:

            res = open_router.tts.create_speech(input=speech_input, model="fish-audio/s2.1-pro-free:free", response_format="mp3", speed=1, voice=voice)
            res.read()

            with open(output_path, "wb") as f:
                f.write(res.content)
        return output_path

class AudioEngineerTools:

    @tool
    def record_rubric_scores(
        loudness_consistency: int,
        noise_clarity: int,
        silence_pacing: int,
        transitions: int,
        technical_compliance: int,
        evidence: str,
        audio_path: str,
        runtime: ToolRuntime,
    ) -> Command:
        """Record your rubric assessment after listening to the current audio.
        Score each dimension 1-5 and cite what you heard as evidence for each."""
        return Command(update={
            "rubric_scores": {
                "loudness_consistency": loudness_consistency,
                "noise_clarity": noise_clarity,
                "silence_pacing": silence_pacing,
                "transitions": transitions,
                "technical_compliance": technical_compliance,
                "evidence": evidence,
                "final_audio_path": audio_path
            },
            "messages": [
                ToolMessage(content="Rubric recorded.", tool_call_id=runtime.tool_call_id)
            ],
        })

    @tool
    def listen_audio(input_path: str):
        "Listen to the current version of the podcast clip"
        with open(input_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
    
        return ToolMessage(content=[
            {"type": "text", "text": "The current podcast clip is the following"},
            {
                "type": "audio",
                "base64": audio_b64,
                "mime_type": "audio/mpeg",
            },
        ])

    @tool
    def generate_audio(script: str, host_or_expert: Literal["Host", "Expert"], output_path: str):
        "Provide the section from the script that should be regenerated because it could not be adjusted by any of the tools"
        if host_or_expert == "Host":
            new_audio_path = VoiceAgentsTools.generate_audio(script, voice="536d3a5e000945adb7038665781a4aca", output_path=output_path)
        elif host_or_expert == "Expert":
            new_audio_path = VoiceAgentsTools.generate_audio(script, voice="933563129e564b19a115bedd57b7406a", output_path=output_path)

        return new_audio_path

    @tool
    def trim_audio(input_path: str, start_ms: int, end_ms: int, output_path: str) -> str:
        """Cut a segment of audio between start_ms and end_ms and save it."""
        audio = AudioSegment.from_file(input_path)
        audio[start_ms:end_ms].export(output_path, format="mp3")
        return output_path

    @tool
    def adjust_volume(input_path: str, change_db: float, output_path: str) -> str:
        """Increase (+) or decrease (-) volume by change_db decibels."""
        audio = AudioSegment.from_file(input_path)
        (audio + change_db).export(output_path, format="mp3")
        return output_path

    @tool
    def fade(input_path: str, fade_in_ms: int, fade_out_ms: int, output_path: str) -> str:
        """Apply fade-in and fade-out to the start/end of a clip."""
        audio = AudioSegment.from_file(input_path)
        audio = audio.fade_in(fade_in_ms).fade_out(fade_out_ms)
        audio.export(output_path, format="mp3")
        return output_path

    @tool
    def trim_silence(input_path: str, silence_thresh_db: int, min_silence_len_ms: int, output_path: str) -> str:
        """Remove leading/trailing silence below silence_thresh_db (e.g. -40)."""
        audio = AudioSegment.from_file(input_path)
        chunks = split_on_silence(audio, min_silence_len=min_silence_len_ms, silence_thresh=silence_thresh_db)
        trimmed = sum(chunks, AudioSegment.empty())
        trimmed.export(output_path, format="mp3")
        return output_path

    @tool
    def overlay_audio(base_path: str, overlay_path: str, position_ms: int, gain_db: float, output_path: str) -> str:
        """Mix a second track (e.g. intro music) onto the base at position_ms, at gain_db relative volume."""
        base = AudioSegment.from_file(base_path)
        overlay = AudioSegment.from_file(overlay_path) + gain_db
        base.overlay(overlay, position=position_ms).export(output_path, format="mp3")
        return output_path