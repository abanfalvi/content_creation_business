import os, frontmatter
import base64
import threading
from pathlib import Path
from e2b import Sandbox, CommandExitException
from typing import Callable, Literal, List, TypeVar
from langchain.tools import tool, ToolRuntime
from langgraph.types import Command

from langchain_core.messages import HumanMessage, ToolMessage

from podcast_generation.settings import DATA_DIR, E2B_TEMPLATE, SKILLS_DIR, project_path

from ..voice_tools import VoiceAgentsTools
from .state import AudioEngineerState

T = TypeVar("T")

# Paths the model passes in are relative to the project root (e.g. data/<slug>/audio_contents/x.mp3);
# project_path() resolves them independently of the working directory.

def _verify_e2b_connection(api_key: str) -> bool:
    e2b_api_key = os.environ.get(api_key)
    if e2b_api_key is None:
        return False
    return True

# Sandbox handles by sandbox_id. Sandbox.connect() is an API round-trip, so reuse the handle
# within this process. A cached handle may point at a sandbox that has since timed out;
# _call_sandbox reconnects (which also resumes a paused sandbox) if a call on it fails.
_SANDBOX_CACHE: dict[str, Sandbox] = {}
_SANDBOX_CACHE_LOCK = threading.Lock()

def kill_sandbox(sandbox_id: str) -> None:
    with _SANDBOX_CACHE_LOCK:
        _SANDBOX_CACHE.pop(sandbox_id, None)
    Sandbox.kill(sandbox_id)  

def _connect_or_create_sandbox(state: AudioEngineerState, *, thread_id: str | None = None, refresh: bool = False) -> Sandbox:
    sandboxId = state.get("sandboxId")
    if sandboxId:
        if not refresh:
            with _SANDBOX_CACHE_LOCK:
                cached = _SANDBOX_CACHE.get(sandboxId)
            if cached is not None:
                return cached
        sandbox = Sandbox.connect(sandbox_id=sandboxId)
    else:
        sandbox = Sandbox.create(
            template=E2B_TEMPLATE,
            timeout=11*60,
            lifecycle={
                "on_timeout": "pause",
                "auto_resume": True
            },
            metadata={"episode_thread": thread_id} if thread_id is not None else None
        )
    with _SANDBOX_CACHE_LOCK:
        _SANDBOX_CACHE[sandbox.sandbox_id] = sandbox
    return sandbox

def _call_sandbox(state: AudioEngineerState, sandbox: Sandbox, op: Callable[[Sandbox], T]) -> T:
    """Run op(sandbox); if it fails, reconnect once (the cached handle may be stale) and retry.
    Command failures (non-zero exit) are real results, not stale handles, so they are not retried."""
    try:
        return op(sandbox)
    except CommandExitException:
        raise
    except Exception:
        if not state.get("sandboxId"):
            raise  # freshly created sandbox, nothing stale to refresh
        return op(_connect_or_create_sandbox(state, refresh=True))

def _open_sandbox(runtime: ToolRuntime[None, AudioEngineerState], *, create: bool = True) -> Sandbox | str:
    """The sandbox for this run, or a message the tool can return to the model if there isn't one.
    With create=False, only an existing sandbox is used; a new one is never started."""
    if not _verify_e2b_connection("E2B_API_KEY"):
        return "Cannot use this tool because the key for E2B is missing. Make sure to signal this in your response."
    if not create and not runtime.state.get("sandboxId"):
        return "There is no sandbox yet, so there is nothing in it to open. Upload or render something first."
    try:
        return _connect_or_create_sandbox(state=runtime.state, thread_id=runtime.execution_info.thread_id)
    except Exception as error:
        return (f"Could not start the sandbox: {error}. (If the E2B template '{E2B_TEMPLATE}' does not exist, "
                "it has to be built first.) Make sure to signal this in your response.")

def _tail(text: str, limit: int = 4000) -> str:
    """Keep the end of long command output. `remotion render` prints one progress line per frame,
    which would otherwise fill the model's context."""
    return text if len(text) <= limit else f"[... {len(text) - limit} earlier characters omitted ...]\n{text[-limit:]}"

def _data_file(path: str) -> Path:
    """Resolve a path the model gave for a local file; it must be inside the project's data/ folder."""
    resolved = project_path(path).resolve()
    if not resolved.is_relative_to(DATA_DIR.resolve()):
        raise ValueError(f"{path} is outside the data/ folder")
    return resolved

def _sandbox_reply(sandbox: Sandbox, runtime: ToolRuntime[None, AudioEngineerState], content: str):
    return Command(
        update={
            "sandboxId": sandbox.sandbox_id,
            "messages": [
                ToolMessage(content=content, tool_call_id=runtime.tool_call_id)
            ]
        }
    )

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
        Score each dimension 1-5 and cite what you heard as evidence for each.
        audio_path must be the finished episode as a local data/... file."""
        # The pipeline copies this path into the episode, so it has to exist locally (not just in the sandbox).
        if not project_path(audio_path).is_file():
            return Command(update={"messages": [ToolMessage(
                content=(f"Not recorded: audio_path '{audio_path}' is not a local file. The final episode must be "
                         "downloaded from the sandbox into the book's audio_contents folder first; pass that local path."),
                tool_call_id=runtime.tool_call_id,
            )]})
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
    async def exec_sbx_command(cmd: str, runtime: ToolRuntime[None, AudioEngineerState], timeout_s: int = 300) -> Command | str:
        """Execute a shell command in the sandbox. It starts in the Remotion project folder
        (/home/user/remotion-project). timeout_s is how long to wait for it to finish (max 600)."""
        sbx = _open_sandbox(runtime)
        if isinstance(sbx, str):
            return sbx
        try:
            result = _call_sandbox(runtime.state, sbx, lambda s: s.commands.run(cmd, timeout=min(max(timeout_s, 1), 600)))
            return _sandbox_reply(sbx, runtime, f"Exit code 0.\nstdout:\n{_tail(result.stdout)}\nstderr:\n{_tail(result.stderr)}")
        except CommandExitException as error:
            return _sandbox_reply(sbx, runtime, f"Command failed (exit code {error.exit_code}).\nstdout:\n{_tail(error.stdout)}\nstderr:\n{_tail(error.stderr)}")
        except Exception as error:
            return _sandbox_reply(sbx, runtime, f"Command did not complete: {error}")

    @tool
    @staticmethod
    def sbx_read(path: str, runtime: ToolRuntime[None, AudioEngineerState]) -> Command | str:
        "Read the content of the file stored in the active sandbox"
        sbx = _open_sandbox(runtime)
        if isinstance(sbx, str):
            return sbx
        try:
            file_content = _call_sandbox(runtime.state, sbx, lambda s: s.files.read(path))
            return _sandbox_reply(sbx, runtime, file_content)
        except:
            entries = sbx.files.list("/home/user")
            return _sandbox_reply(sbx, runtime, f"File not found: ${path}. Files in /home/user: {", ".join(entry.name for entry in entries)}")

    @tool
    @staticmethod
    def sbx_write(path: str, content: str, runtime: ToolRuntime[None, AudioEngineerState]) -> Command | str:
        "Create or overwrite a text file in the sandbox (e.g. a Remotion composition)"
        sbx = _open_sandbox(runtime)
        if isinstance(sbx, str):
            return sbx
        try:
            _call_sandbox(runtime.state, sbx, lambda s: s.files.write(path, content))
            return _sandbox_reply(sbx, runtime, f"Saved {path} in the sandbox. Run it with exec_sbx_command.")
        except Exception as error:
            return _sandbox_reply(sbx, runtime, f"Could not write {path}: {error}")

    @tool
    @staticmethod
    def sbx_upload(local_path: str, sandbox_path: str, runtime: ToolRuntime[None, AudioEngineerState]) -> Command | str:
        """Copy a file from the project's data/ folder into the sandbox, e.g. an audio clip into
        /home/user/remotion-project/public/ so a Remotion composition can use it."""
        sbx = _open_sandbox(runtime)
        if isinstance(sbx, str):
            return sbx
        try:
            src = _data_file(local_path)

            def upload(s: Sandbox):
                with open(src, "rb") as f:
                    s.files.write(sandbox_path, f)

            _call_sandbox(runtime.state, sbx, upload)
            return _sandbox_reply(sbx, runtime, f"Uploaded {local_path} to {sandbox_path} in the sandbox.")
        except Exception as error:
            return _sandbox_reply(sbx, runtime, f"Could not upload {local_path}: {error}")

    @tool
    @staticmethod
    def sbx_download(sandbox_path: str, local_path: str, runtime: ToolRuntime[None, AudioEngineerState]) -> Command | str:
        """Copy a file from the sandbox into the project's data/ folder, e.g. a rendered mp3 into
        the book's audio_contents folder. Overwrites local_path if it exists."""
        sbx = _open_sandbox(runtime)
        if isinstance(sbx, str):
            return sbx
        try:
            dest = _data_file(local_path)
            data = _call_sandbox(runtime.state, sbx, lambda s: s.files.read(sandbox_path, format="bytes"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(bytes(data))
            return _sandbox_reply(sbx, runtime, f"Downloaded {sandbox_path} to {local_path} ({len(data)} bytes). Listen to it before trusting it.")
        except Exception as error:
            return _sandbox_reply(sbx, runtime, f"Could not download {sandbox_path}: {error}")

    @tool
    @staticmethod
    def listen_audio(input_path: str, runtime: ToolRuntime[None, AudioEngineerState], in_sandbox: bool = False) -> Command | str:
        """Listen to an audio file. By default input_path is a local data/... path. Set in_sandbox=True
        to listen to a file inside the sandbox (e.g. /home/user/remotion-project/out/episode.mp3)
        directly."""
        update: dict = {}
        if in_sandbox:
            sbx = _open_sandbox(runtime, create=False)
            if isinstance(sbx, str):
                return sbx
            try:
                audio = bytes(_call_sandbox(runtime.state, sbx, lambda s: s.files.read(input_path, format="bytes")))
            except Exception as error:
                return _sandbox_reply(sbx, runtime, f"Could not read {input_path} from the sandbox: {error}")
            update["sandboxId"] = sbx.sandbox_id
        else:
            with open(project_path(input_path), "rb") as f:
                audio = f.read()

        where = "in the sandbox" if in_sandbox else "locally"
        update["messages"] = [
            ToolMessage(content="Audio loaded — see the attached clip below.", tool_call_id=runtime.tool_call_id),
            HumanMessage(content=[
                {"type": "text", "text": f"The current podcast clip ({input_path}, {where}) is the following:"},
                {
                    "type": "audio",
                    "base64": base64.b64encode(audio).decode("utf-8"),
                    "mime_type": "audio/wav" if input_path.lower().endswith(".wav") else "audio/mpeg",
                },
            ]),
        ]
        return Command(update=update)

    @tool
    @staticmethod
    def generate_audio(script: str, host_or_expert: Literal["Host", "Expert"], output_path: str):
        "Provide the section from the script that should be regenerated because editing could not fix it"
        if host_or_expert == "Host":
            new_audio_path = VoiceAgentsTools.generate_audio(script, voice="536d3a5e000945adb7038665781a4aca", output_path=output_path)
        elif host_or_expert == "Expert":
            new_audio_path = VoiceAgentsTools.generate_audio(script, voice="933563129e564b19a115bedd57b7406a", output_path=output_path)

        return new_audio_path

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
