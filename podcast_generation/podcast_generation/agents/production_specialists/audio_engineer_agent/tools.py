import os, frontmatter
import base64
from pathlib import Path
from typing import Literal, List
from langchain.tools import tool, ToolRuntime
from langgraph.types import Command

from langchain_core.messages import HumanMessage, ToolMessage

from podcast_generation.media import get_audio_segment
from podcast_generation.settings import SKILLS_DIR, project_path

from ..voice_tools import VoiceAgentsTools

# Paths the model passes in are relative to the project root (e.g. data/<slug>/audio_contents/x.mp3);
# project_path() resolves them independently of the working directory. pydub/ffmpeg are set up
# on first use (get_audio_segment), not at import, because static-ffmpeg downloads its binaries.


class AudioEngineerTools:

    @tool
    @staticmethod
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
    @staticmethod
    def listen_audio(input_path: str, runtime: ToolRuntime) -> Command:
        "Listen to the current version of the podcast clip"
        with open(project_path(input_path), "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("utf-8")

        return Command(update={
            "messages": [

                ToolMessage(content="Audio loaded — see the attached clip below.", tool_call_id=runtime.tool_call_id),
                HumanMessage(content=[
                    {"type": "text", "text": f"The current podcast clip ({input_path}) is the following:"},
                    {
                        "type": "audio",
                        "base64": audio_b64,
                        "mime_type": "audio/mpeg",
                    },
                ]),
            ],
        })

    @tool
    @staticmethod
    def generate_audio(script: str, host_or_expert: Literal["Host", "Expert"], output_path: str):
        "Provide the section from the script that should be regenerated because it could not be adjusted by any of the tools"
        if host_or_expert == "Host":
            new_audio_path = VoiceAgentsTools.generate_audio(script, voice="536d3a5e000945adb7038665781a4aca", output_path=output_path)
        elif host_or_expert == "Expert":
            new_audio_path = VoiceAgentsTools.generate_audio(script, voice="933563129e564b19a115bedd57b7406a", output_path=output_path)

        return new_audio_path

    @tool
    @staticmethod
    def trim_audio(input_path: str, start_ms: int, end_ms: int, output_path: str) -> str:
        """Cut a segment of audio between start_ms and end_ms and save it."""
        AudioSegment = get_audio_segment()
        audio = AudioSegment.from_file(project_path(input_path))
        audio[start_ms:end_ms].export(project_path(output_path), format="mp3")
        return output_path

    @tool
    @staticmethod
    def adjust_volume(input_path: str, change_db: float, output_path: str) -> str:
        """Increase (+) or decrease (-) volume by change_db decibels."""
        AudioSegment = get_audio_segment()
        audio = AudioSegment.from_file(project_path(input_path))
        (audio + change_db).export(project_path(output_path), format="mp3")
        return output_path

    @tool
    @staticmethod
    def fade(input_path: str, fade_in_ms: int, fade_out_ms: int, output_path: str) -> str:
        """Apply fade-in and fade-out to the start/end of a clip."""
        AudioSegment = get_audio_segment()
        audio = AudioSegment.from_file(project_path(input_path))
        audio = audio.fade_in(fade_in_ms).fade_out(fade_out_ms)
        audio.export(project_path(output_path), format="mp3")
        return output_path

    @tool
    @staticmethod
    def trim_silence(input_path: str, silence_thresh_db: int, min_silence_len_ms: int, output_path: str) -> str:
        """Remove leading/trailing silence below silence_thresh_db (e.g. -40)."""
        AudioSegment = get_audio_segment()
        from pydub.silence import split_on_silence

        audio = AudioSegment.from_file(project_path(input_path))
        chunks = split_on_silence(audio, min_silence_len=min_silence_len_ms, silence_thresh=silence_thresh_db)
        trimmed = sum(chunks, AudioSegment.empty())
        trimmed.export(project_path(output_path), format="mp3")
        return output_path

    @tool
    @staticmethod
    def overlay_audio(base_path: str, overlay_path: str, position_ms: int, gain_db: float, output_path: str) -> str:
        """Mix a second track (e.g. intro music) onto the base at position_ms, at gain_db relative volume."""
        AudioSegment = get_audio_segment()
        base = AudioSegment.from_file(project_path(base_path))
        overlay = AudioSegment.from_file(project_path(overlay_path)) + gain_db
        base.overlay(overlay, position=position_ms).export(project_path(output_path), format="mp3")
        return output_path

    @tool
    @staticmethod
    def load_skill_content(skill_name: str) -> str:
        "Load the content of the specific skill"
        post = frontmatter.load(SKILLS_DIR / "production_skills" / f"{skill_name}.md")
        return post.content

    @tool
    @staticmethod
    def load_available_skills() -> List[dict] | str:
        "Load the name and descriptions of the available skills"
        skills_dir = SKILLS_DIR / "production_skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        all_skills = list(skills_dir.glob("*.md"))
        if all_skills:
            all_metadata = []
            for skill in all_skills:
                post = frontmatter.load(skill)
                all_metadata.append(post.metadata)
            return all_metadata
        else:
            return "No skills available yet!"
