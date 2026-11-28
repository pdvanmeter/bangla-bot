import os
import re
import sys
import time
import ctypes
import tempfile
import threading
import subprocess
from io import BytesIO
from typing import Any
from gtts import gTTS
from google.genai import types

PRIMARY_MODEL = "gemini-3.5-flash"
AVAILABLE_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-2.5-flash",
]

# In-memory cache of Bengali text -> MP3 bytes for instant audio playback
_tts_cache: dict[str, bytes] = {}
_tts_lock = threading.Lock()
_playback_lock = threading.Lock()


def build_generate_config(
    model_name: str,
    system_instructions: str,
    tools: list[Any] | None = None,
) -> types.GenerateContentConfig:
    """Creates GenerateContentConfig with session-scoped tools and thinking_budget=0 on Gemini 2.5/3.x."""
    kwargs: dict[str, Any] = dict(
        system_instruction=system_instructions,
        tools=tools or [],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False),
    )
    if "gemini-3" in model_name or "gemini-2.5" in model_name:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)


def extract_audio_segments(text: str) -> list[str]:
    """Extracts all <audio>...</audio> segments from a tutor response."""
    if not text:
        return []
    return [
        seg.strip()
        for seg in re.findall(r"<audio>(.*?)</audio>", text, flags=re.DOTALL)
        if seg.strip()
    ]


def strip_audio_tags(text: str) -> str:
    """Removes <audio>...</audio> tags while preserving the inner Bengali text."""
    if not text:
        return ""
    return re.sub(r"</?audio>", "", text).strip()


def fetch_tts_bytes(bengali_text: str) -> bytes | None:
    """Generates or retrieves cached TTS MP3 bytes for the given Bengali text."""
    text = bengali_text.strip()
    if not text:
        return None
    with _tts_lock:
        if text in _tts_cache:
            return _tts_cache[text]
    try:
        tts = gTTS(text=text, lang="bn")
        fp = BytesIO()
        tts.write_to_fp(fp)
        data = fp.getvalue()
        with _tts_lock:
            _tts_cache[text] = data
        return data
    except Exception as e:
        print(f"TTS Error: {e}")
        return None


def prefetch_audio_segments(segments: list[str]):
    """Pre-fetches TTS audio in a background thread so playback is instant."""
    if not segments:
        return

    def _worker():
        for seg in segments:
            fetch_tts_bytes(seg)

    threading.Thread(target=_worker, daemon=True).start()


def _play_mp3_file_windows(file_path: str):
    """Plays an MP3 file synchronously using Windows MCI (winmm.dll) without spawning PowerShell."""
    alias = f"bangla_tts_{int(time.time() * 1000)}"
    winmm = ctypes.windll.winmm
    buf = ctypes.create_unicode_buffer(256)

    def mci(cmd: str) -> int:
        return winmm.mciSendStringW(cmd, buf, 255, 0)

    rc = mci(f'open "{file_path}" type mpegvideo alias {alias}')
    if rc != 0:
        return
    try:
        mci(f"play {alias} wait")
    finally:
        mci(f"close {alias}")


def play_audio_segment(bengali_text: str):
    """Fetches (or uses cached) TTS audio and plays it synchronously across Windows, macOS, and Linux."""
    mp3_bytes = fetch_tts_bytes(bengali_text)
    if not mp3_bytes:
        return

    with _playback_lock:
        fd, temp_path = tempfile.mkstemp(suffix=".mp3")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(mp3_bytes)

            if os.name == "nt":
                _play_mp3_file_windows(os.path.abspath(temp_path))
            elif sys.platform == "darwin":
                subprocess.run(["afplay", temp_path], check=False)
            else:
                subprocess.run(["mpg123", "-q", temp_path], check=False)
        except Exception as e:
            print(f"\n[Audio Error: Could not play audio. {e}]")
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass


def play_audio_segments(segments: list[str]):
    """Plays a list of Bengali text segments sequentially."""
    for seg in segments:
        play_audio_segment(seg)
