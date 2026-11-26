import asyncio
import base64
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from podcast_generation.agents.models import TRANSCRIPTION_MODEL
from podcast_generation.media import ensure_ffmpeg
from podcast_generation.settings import require_env

CHUNK_SECONDS = 300      # audio is sent in parts of about this length: providers time out after about a minute
CUT_SLACK_SECONDS = 45   # a cut may move this far from its target, to land in a pause rather than mid-word
STT_CONCURRENCY = 4      # parts transcribed at the same time
AUDIO_KBPS = 48          # mono, 16 kHz: plenty for speech, about 20 MB per hour
PARAGRAPH_WORDS = 90
HEADER_END = "\n---\n"   # the transcript's header ends here; the speech follows

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}
_ID = re.compile(r"^[\w-]{11}$")
_TIME = re.compile(r"^\[((?:\d+:)?\d{2}:\d{2})\]\s*")
_STAMP_LINE = re.compile(r"^\[((?:\d+:)?\d{2}:\d{2})\]", re.M)
_YDL_OPTS = {
    "quiet": True,
    "noprogress": True,
    "no_warnings": True,
    "noplaylist": True,
    # YouTube needs a JavaScript runtime to unscramble its media URLs; use whichever of these is installed.
    "js_runtimes": {"deno": {}, "node": {}},
}


class VideoError(Exception):
    """A video that cannot be read, downloaded or transcribed; the message is meant for the user."""


# URLs and titles ------------------------------------------------------------------
def video_id(url: str) -> str | None:
    """The 11-character id of a single YouTube video link, or None if the text is not one."""
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() not in _YOUTUBE_HOSTS:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if (parsed.hostname or "").lower().endswith("youtu.be"):
        candidate = parts[0] if parts else ""
    elif parts[:1] == ["watch"]:
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    elif parts[:1] in (["shorts"], ["live"], ["embed"], ["v"]) and len(parts) > 1:
        candidate = parts[1]
    else:
        return None
    return candidate if _ID.match(candidate) else None


def canonical_url(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"


def clean_title(title: str) -> str:
    """A video title that is safe to use as a folder name (the book slug is derived from it)."""
    title = re.sub(r'[\\/*?"<>|\x00-\x1f]+', " ", title)
    return re.sub(r"\s+", " ", title).strip(" .")[:100].strip(" .")


def _message(exc: Exception) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).strip().removeprefix("ERROR:").strip()
    return text[:300] or type(exc).__name__


def stamp_seconds(stamp: str) -> int:
    """Seconds in a transcript time stamp: "05:30" -> 330, "1:02:03" -> 3723."""
    seconds = 0
    for part in stamp.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def clock(seconds: float) -> str:
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


# yt-dlp ---------------------------------------------------------------------------
def fetch_video_info(url: str) -> dict:
    """Title, channel and length of a video, without downloading it."""
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL({**_YDL_OPTS, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise VideoError(_message(exc)) from exc
    return {
        "id": info.get("id", ""),
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration": int(info.get("duration") or 0),
        "is_live": bool(info.get("is_live")),
    }


def download_audio(url: str, out_dir: Path) -> Path:
    """Download a video's audio as mono 16 kHz mp3 into `out_dir`."""
    import yt_dlp

    ffmpeg, _ = ensure_ffmpeg()
    opts = {
        **_YDL_OPTS,
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "audio.%(ext)s"),
        "ffmpeg_location": os.path.dirname(ffmpeg),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": str(AUDIO_KBPS)}],
        "postprocessor_args": {"extractaudio": ["-ac", "1", "-ar", "16000"]},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise VideoError(_message(exc)) from exc
    audio = out_dir / "audio.mp3"
    if not audio.is_file():
        raise VideoError("The audio could not be downloaded.")
    return audio


# Splitting ------------------------------------------------------------------------
def choose_cuts(silences: list[float], duration: float, target: float = CHUNK_SECONDS, slack: float = CUT_SLACK_SECONDS) -> list[float]:
    """Where to cut the audio: about every `target` seconds, at the pause nearest each target (within `slack`)."""
    cuts: list[float] = []
    pos = 0.0
    while duration - pos > target + slack:
        near = [s for s in silences if abs(s - (pos + target)) <= slack and s > pos]
        pos = min(near, key=lambda s: abs(s - (pos + target))) if near else pos + target
        cuts.append(pos)
    return cuts


def _probe_silences(ffmpeg: str, audio: Path) -> tuple[float, list[float]]:
    """(duration, midpoints of the pauses) of an audio file, from one streaming pass of ffmpeg's silencedetect."""
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(audio), "-af", "silencedetect=noise=-35dB:d=0.35", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    log = proc.stderr
    stamp = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", log)
    duration = int(stamp[1]) * 3600 + int(stamp[2]) * 60 + float(stamp[3]) if stamp else 0.0
    starts = [float(x) for x in re.findall(r"silence_start: (-?\d+(?:\.\d+)?)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: (\d+(?:\.\d+)?)", log)]
    return duration, [(s + e) / 2 for s, e in zip(starts, ends)]


def split_audio(audio: Path, out_dir: Path) -> list[tuple[float, Path]]:
    """Cut the audio into parts of about CHUNK_SECONDS at pauses. Returns (start second, file) for each part."""
    ffmpeg, _ = ensure_ffmpeg()
    duration, silences = _probe_silences(ffmpeg, audio)
    cuts = choose_cuts(silences, duration)
    if not cuts:
        return [(0.0, audio)]
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(audio), "-f", "segment",
         "-segment_times", ",".join(f"{c:.3f}" for c in cuts), "-c", "copy", "-reset_timestamps", "1",
         str(out_dir / "part_%03d.mp3")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    parts = sorted(out_dir.glob("part_*.mp3"))
    if proc.returncode != 0 or len(parts) != len(cuts) + 1:
        raise VideoError(f"The audio could not be split: {proc.stderr.strip()[-200:]}")
    return list(zip([0.0, *cuts], parts))


# Transcription --------------------------------------------------------------------
async def _transcribe_parts(parts: list[Path], on_progress=lambda done, total: None) -> list[str]:
    from openrouter import OpenRouter, components, utils

    # Failed requests are retried with backoff, but not for an hour (the SDK default).
    retries = utils.RetryConfig("backoff", utils.BackoffStrategy(1000, 30_000, 1.5, 180_000), True)
    limit = asyncio.Semaphore(STT_CONCURRENCY)
    finished = 0

    async with OpenRouter(api_key=require_env("OPENROUTER_API_KEY")) as client:
        async def transcribe(i: int, path: Path) -> str:
            nonlocal finished
            async with limit:
                data = base64.b64encode(await asyncio.to_thread(path.read_bytes)).decode()
                try:
                    res = await client.stt.create_transcription_async(
                        input_audio=components.STTInlineInputAudio(data=data, format="mp3"),
                        model=TRANSCRIPTION_MODEL, retries=retries, timeout_ms=120_000,
                    )
                except Exception as exc:  # noqa: BLE001 - say which part failed
                    raise VideoError(f"Transcribing part {i + 1} of {len(parts)} failed: {_message(exc)}") from exc
                finished += 1
                on_progress(finished, len(parts))
                return res.text.strip()

        tasks = [asyncio.create_task(transcribe(i, p)) for i, p in enumerate(parts)]
        try:
            return list(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                task.cancel()
            raise


def paragraphs(text: str, target: int = PARAGRAPH_WORDS, hard: int = 2 * PARAGRAPH_WORDS) -> list[str]:
    """Group sentences into paragraphs of about `target` words (a run with no punctuation is cut at `hard` words)."""
    out: list[str] = []
    current: list[str] = []
    count = 0

    def flush() -> None:
        nonlocal current, count
        if current:
            out.append(" ".join(current))
        current, count = [], 0

    for sentence in re.split(r"(?<=[.!?…])\s+", " ".join(text.split())):
        words = sentence.split()
        while len(words) > hard:
            flush()
            out.append(" ".join(words[:hard]))
            words = words[hard:]
        if not words:
            continue
        current.append(" ".join(words))
        count += len(words)
        if count >= target:
            flush()
    flush()
    return out


def build_transcript(title: str, channel: str, url: str, duration: float, parts: list[tuple[float, str]]) -> str:
    """The transcript file: a header, a rule, then the paragraphs, each part opening with its start time."""
    lines = [
        f"# {title}", "",
        f"Source: YouTube video{f' by {channel}' if channel else ''}, {url}",
        f"Duration: {clock(duration)}", "", "---", "",
    ]
    for start, text in parts:
        for i, paragraph in enumerate(paragraphs(text)):
            lines += [f"[{clock(start)}] {paragraph}" if i == 0 else paragraph, ""]
    return "\n".join(lines)


def is_transcript(markdown: str) -> bool:
    """Whether the text is a transcript file made by `build_transcript` (not a book)."""
    return markdown.startswith("# ") and "\nSource: YouTube video" in markdown.split(HEADER_END, 1)[0]


def stamp_offsets(markdown: str) -> list[tuple[int, str]]:
    """(character offset, time stamp) of every time stamp a transcript opens a part with, in order."""
    return [(m.start(), m.group(1)) for m in _STAMP_LINE.finditer(markdown)]


def split_transcript(markdown: str) -> list[tuple[str, str]]:
    """(time stamp, text) of every paragraph of a transcript file; the stamp is the last one seen at or before it."""
    body = markdown.split(HEADER_END, 1)[1] if HEADER_END in markdown else markdown
    out: list[tuple[str, str]] = []
    stamp = "00:00"
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        found = _TIME.match(block)
        if found:
            stamp, block = found.group(1), block[found.end():]
        out.append((stamp, block))
    return out


async def transcribe_audio(
    audio: Path, work_dir: Path, title: str, channel: str, url: str, duration: float, on_progress=lambda done, total: None,
) -> str:
    """Transcribe an audio file and return the transcript file's text."""
    pieces = await asyncio.to_thread(split_audio, audio, work_dir)
    texts = await _transcribe_parts([path for _, path in pieces], on_progress)
    if not any(t.split() for t in texts):
        raise VideoError("No speech was found in this video.")
    return build_transcript(title, channel, url, duration, [(start, text) for (start, _), text in zip(pieces, texts)])
