"""Lazy ffmpeg / pydub setup.

static-ffmpeg downloads its binaries on first use, so this must not run at import time.
Call `get_audio_segment()` where pydub is needed instead of importing it at module level.
"""
import os
from functools import cache


@cache
def ensure_ffmpeg() -> tuple[str, str]:
    """Fetch (first time only) and return the paths of static-ffmpeg's ffmpeg and ffprobe."""
    from static_ffmpeg import run as static_ffmpeg_run

    ffmpeg, ffprobe = static_ffmpeg_run.get_or_fetch_platform_executables_else_raise()
    # Some pydub internals (e.g. mediainfo_json, used by from_mp3/from_file) re-resolve
    # ffmpeg/ffprobe through a fresh PATH search on every call instead of reading
    # AudioSegment.converter/.ffprobe, so pinning those attributes alone is not enough.
    os.environ["PATH"] = os.path.dirname(ffmpeg) + os.pathsep + os.environ.get("PATH", "")
    return ffmpeg, ffprobe


@cache
def get_audio_segment():
    """Return pydub's AudioSegment, configured to use static-ffmpeg."""
    ffmpeg, ffprobe = ensure_ffmpeg()
    # Imported only after PATH is set so pydub does not warn that ffmpeg is missing.
    from pydub import AudioSegment

    AudioSegment.converter = ffmpeg
    AudioSegment.ffmpeg = ffmpeg
    AudioSegment.ffprobe = ffprobe
    return AudioSegment
