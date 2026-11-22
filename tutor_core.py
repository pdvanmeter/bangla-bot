import os
import re
import sys
import json
import time
import ctypes
import tempfile
import threading
import subprocess
from io import BytesIO
from gtts import gTTS
from google.genai import types

PROGRESS_FILE = "progress.json"
VOCAB_CURRICULUM_FILE = os.path.join("curriculum", "vocabulary.json")
GRAMMAR_CURRICULUM_FILE = os.path.join("curriculum", "grammar.json")

PRIMARY_MODEL = "gemini-3.5-flash"
AVAILABLE_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-2.5-flash",
]

# Optional callback triggered when record_practice_result updates disk
_progress_callbacks = []

# In-memory cache of Bengali text -> MP3 bytes for instant audio playback
_tts_cache: dict[str, bytes] = {}
_tts_lock = threading.Lock()
_playback_lock = threading.Lock()


def register_progress_callback(callback):
    """Registers a callback(category, item_key, is_correct, new_score) for UI notifications."""
    _progress_callbacks.append(callback)


def ensure_progress_file() -> dict:
    """Ensures progress.json exists on disk with the initial schema and returns its contents."""
    default_data = {"vocabulary": {}, "grammar": {}}
    if not os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(default_data, f, ensure_ascii=False, indent=2)
        return default_data
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = default_data
    except (json.JSONDecodeError, OSError):
        data = default_data

    changed = False
    if "vocabulary" not in data or not isinstance(data["vocabulary"], dict):
        data["vocabulary"] = {}
        changed = True
    if "grammar" not in data or not isinstance(data["grammar"], dict):
        data["grammar"] = {}
        changed = True
    if changed:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def read_progress():
    """Reads the current learner's progress from progress.json, creating it if missing."""
    return ensure_progress_file()


def record_practice_result(
    category: str,
    item_key: str,
    is_correct: bool,
    initial_mastery: float = 0.3,
):
    """
    Updates progress for a vocabulary word or grammar concept.

    Args:
        category: "vocabulary" or "grammar"
        item_key: The transliterated word or grammar concept name.
        is_correct: Whether the user was correct.
        initial_mastery: (0.0 to 0.5) Optional initial score for the first encounter.
    """
    try:
        data = ensure_progress_file()

        target_cat = data.get(category)
        if target_cat is None:
            return f"Error: Invalid category '{category}'. Use 'vocabulary' or 'grammar'."

        today = time.strftime("%Y-%m-%d")

        if item_key not in target_cat:
            mastery = max(0.0, min(0.5, float(initial_mastery)))
            target_cat[item_key] = {
                "encounters": 1,
                "mastery_score": round(mastery, 2),
                "last_practiced": today,
            }
        else:
            stats = target_cat[item_key]
            stats["encounters"] = stats.get("encounters", 0) + 1
            adjustment = 0.1 if is_correct else -0.1
            new_mastery = stats.get("mastery_score", 0.0) + adjustment
            stats["mastery_score"] = round(max(0.0, min(1.0, new_mastery)), 2)
            stats["last_practiced"] = today

        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        score = data[category][item_key]["mastery_score"]
        print(f"--- [Disk] Updated {category}: {item_key} (Mastery: {score}) ---")

        for cb in _progress_callbacks:
            try:
                cb(category, item_key, is_correct, score)
            except Exception as cb_err:
                print(f"Callback error: {cb_err}")

        return f"Progress recorded successfully for {item_key} (new mastery_score: {score})."
    except Exception as e:
        print(f"Error recording progress: {e}")
        return f"Error: {str(e)}"


def read_vocabulary_curriculum():
    """Reads the stable vocabulary curriculum from curriculum/vocabulary.json."""
    if not os.path.exists(VOCAB_CURRICULUM_FILE):
        return {"error": "Vocabulary curriculum file not found."}
    with open(VOCAB_CURRICULUM_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def read_grammar_curriculum():
    """Reads the stable grammar curriculum from curriculum/grammar.json."""
    if not os.path.exists(GRAMMAR_CURRICULUM_FILE):
        return {"error": "Grammar curriculum file not found."}
    with open(GRAMMAR_CURRICULUM_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


TOOLS = [
    read_progress,
    record_practice_result,
    read_vocabulary_curriculum,
    read_grammar_curriculum,
]


def load_system_instructions() -> str:
    """Loads GEMINI.md and embeds the static curriculum and initial progress to avoid startup tool round-trips."""
    with open("GEMINI.md", "r", encoding="utf-8") as f:
        base_instructions = f.read()

    vocab = read_vocabulary_curriculum()
    grammar = read_grammar_curriculum()
    progress = read_progress()

    preloaded_context = (
        "\n\n# Pre-loaded Session Context (Optimization)\n"
        "To minimize response latency, the curriculum and initial learner progress are already loaded below. "
        "You do NOT need to call `read_vocabulary_curriculum`, `read_grammar_curriculum`, or `read_progress` "
        "at the start of the session—use the data below directly. "
        "You MUST still call `record_practice_result` after the user responds to practice tasks.\n\n"
        f"## Current Progress (`progress.json`)\n```json\n{json.dumps(progress, ensure_ascii=False)}\n```\n\n"
        f"## Grammar Curriculum (`curriculum/grammar.json`)\n```json\n{json.dumps(grammar, ensure_ascii=False)}\n```\n\n"
        f"## Vocabulary Curriculum (`curriculum/vocabulary.json`)\n```json\n{json.dumps(vocab, ensure_ascii=False)}\n```\n"
    )
    return base_instructions + preloaded_context


def build_generate_config(model_name: str, system_instructions: str) -> types.GenerateContentConfig:
    """Creates GenerateContentConfig with thinking_budget=0 on Gemini 3.x models for fast responses."""
    kwargs = dict(
        system_instruction=system_instructions,
        tools=TOOLS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False),
    )
    if "gemini-3" in model_name:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)


def extract_audio_segments(text: str) -> list[str]:
    """Extracts all <audio>...</audio> segments from a tutor response."""
    if not text:
        return []
    return [seg.strip() for seg in re.findall(r"<audio>(.*?)</audio>", text, flags=re.DOTALL) if seg.strip()]


def strip_audio_tags(text: str) -> str:
    """Removes <audio>...</audio> tags (keeping the inner Bengali script visible) or strips duplicate tags cleanly."""
    if not text:
        return ""
    # Note: In GEMINI.md, rule 5 says: "Wrap only the Bengali script of a correct sentence in <audio> tags."
    # Often the model writes the sentence inside <audio>...</audio> inline or on its own line.
    # Let's check if the text inside <audio> is already duplicated outside; if not, keep the text or strip carefully.
    # Historically strip_audio_tags removed <audio>...</audio> completely if it was a separate hook,
    # Wait: if the model wraps the Bengali script in <audio>আমি ভাত খাই</audio> inline, removing the whole tag
    # would hide the Bengali script! Let's check how the old strip_audio_tags worked vs inline tags.
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
