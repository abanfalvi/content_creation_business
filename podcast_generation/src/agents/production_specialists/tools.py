from openrouter import OpenRouter
from dotenv import load_dotenv
import os, uuid, frontmatter
import base64
from pathlib import Path
from typing import Literal, List, Tuple, Optional
from langchain.tools import tool, ToolRuntime
from langgraph.types import Command

from langchain_core.messages import HumanMessage, ToolMessage

from pydub import AudioSegment
from pydub.silence import detect_silence, split_on_silence
from pydub.effects import normalize as pydub_normalize

from .state import LLExtractorState

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

    @tool
    def load_skill_content(skill_name: str) -> str:
        "Load the content of the specific skill"
        post = frontmatter.load(f"skills/production_skills/{skill_name}.md")
        return post.content

    @tool
    def load_available_skills() -> List[Tuple[str, str]] | str:
        "Load the name and descriptions of the available skills"
        all_skills = list(Path(r"src\skills\production_skills").iterdir())
        if all_skills:
            all_metadata = []
            for skill in all_skills:
                post = frontmatter.load(skill)
                all_metadata.append(post.metadata)
            return all_metadata
        else:
            return "No skills available yet!"

class LessonsLearnedExtracterAgentTools: # LLExtractorState

    @tool
    def save_learnable_traces(success_trace: bool, title: str, description: str, content: Optional[str], avoid: Optional[str], prefer: Optional[str], runtime: ToolRuntime[None, LLExtractorState]):
        """
        Store both positive and undesired exemplary traces that can be used for improving the specialist agents
        
        Args:
        book_title: str = name of the book that is being processed
        success_trace: bool = whether the current input is to reinforce a behaviour (True) or serve as a negative example (False)
        title: str = a concise summary of the core strategy (e.g., "Navigating Multi-Step Search Filters")
        description: str = one-sentence overview of the item's purpose
        content: str = detailed reasoning steps, decision rationales, and operational insights extracted from past experiences (Use this for desired steps that should be reinforced)
        avoid: str = description of what should be avoided and when (Use this only when you want to add undesired trace)
        prefer: str = description of what should be done instead of the behaviour that should be avoided (Use this only when you want to add undesired trace)

        Output:
        Confirmation that your input has been saved to the persistent local store.
        """
        if success_trace:
            runtime.store.put(("production_traces",), str(uuid.uuid4()), {
                "type": "success",
                "active_agent": "audio_engineer_agent",
                "Title": title, "Description": description, "Content": content,
            })
            return "Successful trace has been saved!"
        else:
            runtime.store.put(("production_traces",), str(uuid.uuid4()), {
                "type": "failure",
                "active_agent": "audio_engineer_agent",
                "Title": title, "Description": description, "Avoid": avoid, "Prefer": prefer
            })
            return "Undesired trace has been saved!"

    @staticmethod
    def extract_learnable_traces(thread_id: str, agent):
        trace = []
        prev_len = 0

        history = list(agent.get_state_history({"configurable": {"thread_id": thread_id}}))
        for snapshot in reversed(history):
            messages = snapshot.values.get("messages", [])
            new_messages = messages[prev_len:]
            prev_len = len(messages)

            for msg in new_messages:
                active_agent = snapshot.values.get("active_agent")
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for call in msg.tool_calls:
                        trace.append({
                            "step": snapshot.metadata["step"],
                            "active_agent": snapshot.values.get("active_agent"),
                            "action": "called_tool",
                            "tool": call["name"],
                            "args": call["args"],
                        })
                elif type(msg).__name__ == "ToolMessage":
                    trace.append({
                        "step": snapshot.metadata["step"],
                        "active_agent": snapshot.values.get("active_agent"),
                        "action": "tool_result",
                        "content": msg.content,
                    })
                elif type(msg).__name__ == "AIMessage":
                    trace.append({
                        "step": snapshot.metadata["step"],
                        "active_agent": snapshot.values.get("active_agent"),
                        "reasoning": "".join(b["reasoning"] for b in msg.content_blocks if b["type"] == "reasoning"),
                        "text": "".join(b["text"] for b in msg.content_blocks if b["type"] == "text"),

                        # "text": msg.text,
                        # "reasoning": msg.reasoning,
                    })
        return trace