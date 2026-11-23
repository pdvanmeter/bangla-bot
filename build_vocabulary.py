#!/usr/bin/env python3
"""
Bengali Vocabulary Expansion Pipeline (Kolkata / Cholitobhasha Dialect)

Pipeline stages:
1. Download & cache OpenSubtitles 2018 Bengali frequency list (bn_50k.txt).
2. Pre-filter non-word noise (ASCII, punctuation, raw digits, stray vowel signs)
   while preserving raw counts for number matching.
3. Pass 1: Batched Gemini API lemmatization, POS tagging, Kolkata phonetic
   transliteration, English translation, dialect/register flagging, and
   English loanword detection (with JSONL checkpointing for resume support).
4. Aggregate inflected forms by (lemma_bengali, pos) and sum frequencies.
5. Pass 2: Batched Gemini AI verification pass (diff-only corrections to save
   output tokens) to audit lemma dictionary forms, Kolkata dialect flags,
   POS tags, and transliterations.
6. Curate the dedicated Bengali numbers table (0-19, tens 20-90, powers of 10,
   plus corpus frequency matching) and export to data/master_numbers.csv.
7. Export master deduplicated vocabulary to data/master_vocabulary.csv.
8. Compile top-K (default 5,000) Kolkata-standard words into per-POS JSON files
   under curriculum/vocabulary/ with unique identifiers and interactive
   overwrite protection.
9. Print a comprehensive breakdown summary across parts of speech.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from enum import Enum
from typing import Any

import requests
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from tutor_core import AVAILABLE_MODELS, PRIMARY_MODEL

FREQUENCY_LIST_URL = (
    "https://raw.githubusercontent.com/hermitdave/FrequencyWords/"
    "master/content/2018/bn/bn_50k.txt"
)

DATA_DIR = "data"
RAW_FREQ_FILE = os.path.join(DATA_DIR, "bn_50k.txt")
CHECKPOINT_DIR = os.path.join(DATA_DIR, "checkpoints")
PASS1_CHECKPOINT = os.path.join(CHECKPOINT_DIR, "pass1_lemmas.jsonl")
PASS2_CHECKPOINT = os.path.join(CHECKPOINT_DIR, "pass2_verified.jsonl")

DEFAULT_MASTER_VOCAB_CSV = os.path.join(DATA_DIR, "master_vocabulary.csv")
DEFAULT_MASTER_NUMBERS_CSV = os.path.join(DATA_DIR, "master_numbers.csv")
DEFAULT_VOCAB_JSON_DIR = os.path.join("curriculum", "vocabulary")

# Bengali Unicode ranges and character classes
BENGALI_CHAR_RE = re.compile(r"^[\u0980-\u09FF]+$")
BENGALI_DIGIT_ONLY_RE = re.compile(r"^[\u09E6-\u09EF]+$")
BENGALI_HAS_LETTER_RE = re.compile(r"[\u0985-\u09B9\u09DC-\u09DF\u09F0-\u09F1]")
STRAY_DIACRITIC_START_RE = re.compile(r"^[\u0981-\u0983\u09BC-\u09CD\u09D7]")

BENGALI_DIGITS_MAP = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def to_bengali_numeral(num: int) -> str:
    return str(num).translate(BENGALI_DIGITS_MAP)


# =====================================================================
# Curated Reference Table for Bengali Cardinal Numbers
# Includes 0-19 (irregular teen patterns), tens 20-90, and powers of 10
# =====================================================================
CURATED_NUMBERS: list[dict[str, Any]] = [
    {
        "numeric_value": 0,
        "bengali_word": "শূন্য",
        "transliteration": "shunno",
        "english": "zero",
        "variants": ["শূন্য"],
        "notes": "Base cardinal 0",
    },
    {
        "numeric_value": 1,
        "bengali_word": "এক",
        "transliteration": "ek",
        "english": "one",
        "variants": ["এক", "একটা", "একটি", "একজন"],
        "notes": "Base cardinal 1",
    },
    {
        "numeric_value": 2,
        "bengali_word": "দুই",
        "transliteration": "dui",
        "english": "two",
        "variants": ["দুই", "দুটো", "দুটি", "দু", "দুজন"],
        "notes": "Base cardinal 2",
    },
    {
        "numeric_value": 3,
        "bengali_word": "তিন",
        "transliteration": "tin",
        "english": "three",
        "variants": ["তিন", "তিনটে", "তিনটি", "তিনজন"],
        "notes": "Base cardinal 3",
    },
    {
        "numeric_value": 4,
        "bengali_word": "চার",
        "transliteration": "char",
        "english": "four",
        "variants": ["চার", "চারটে", "চারটি", "চারজন"],
        "notes": "Base cardinal 4",
    },
    {
        "numeric_value": 5,
        "bengali_word": "পাঁচ",
        "transliteration": "pãch",
        "english": "five",
        "variants": ["পাঁচ", "পাঁচটা", "পাঁচটি"],
        "notes": "Base cardinal 5",
    },
    {
        "numeric_value": 6,
        "bengali_word": "ছয়",
        "transliteration": "chhoy",
        "english": "six",
        "variants": ["ছয়", "ছয়", "ছটা", "ছটি", "ছ"],
        "notes": "Base cardinal 6",
    },
    {
        "numeric_value": 7,
        "bengali_word": "সাত",
        "transliteration": "shaat",
        "english": "seven",
        "variants": ["সাত", "সাতটা", "সাতটি"],
        "notes": "Base cardinal 7",
    },
    {
        "numeric_value": 8,
        "bengali_word": "আট",
        "transliteration": "aat",
        "english": "eight",
        "variants": ["আট", "আটটা", "আটটি"],
        "notes": "Base cardinal 8",
    },
    {
        "numeric_value": 9,
        "bengali_word": "নয়",
        "transliteration": "noy",
        "english": "nine",
        "variants": ["নটা", "নটি", "নয়টা", "নয়টা", "নয়টি", "নয়টি"],
        "notes": "Base cardinal 9 (excludes bare নয়/নয় homograph 'is not' from frequency sum)",
    },
    {
        "numeric_value": 10,
        "bengali_word": "দশ",
        "transliteration": "dosh",
        "english": "ten",
        "variants": ["দশ", "দশটা", "দশটি"],
        "notes": "Base cardinal 10",
    },
    {
        "numeric_value": 11,
        "bengali_word": "এগারো",
        "transliteration": "egaro",
        "english": "eleven",
        "variants": ["এগারো", "এগার", "এগারোটা"],
        "notes": "Irregular teen (11-18 end in -o)",
    },
    {
        "numeric_value": 12,
        "bengali_word": "বারো",
        "transliteration": "baro",
        "english": "twelve",
        "variants": ["বারো", "বারোটা", "বারোটি"],
        "notes": "Irregular teen (excludes bare বার homograph 'time/turn')",
    },
    {
        "numeric_value": 13,
        "bengali_word": "তেরো",
        "transliteration": "tero",
        "english": "thirteen",
        "variants": ["তেরো", "তের", "তেরোটা"],
        "notes": "Irregular teen",
    },
    {
        "numeric_value": 14,
        "bengali_word": "চৌদ্দ",
        "transliteration": "chouddo",
        "english": "fourteen",
        "variants": ["চৌদ্দ", "চৌদ্দো", "চৌদ্দটা"],
        "notes": "Irregular teen",
    },
    {
        "numeric_value": 15,
        "bengali_word": "পনেরো",
        "transliteration": "ponero",
        "english": "fifteen",
        "variants": ["পনেরো", "পনের", "পনেরোটা"],
        "notes": "Irregular teen",
    },
    {
        "numeric_value": 16,
        "bengali_word": "ষোলো",
        "transliteration": "sholo",
        "english": "sixteen",
        "variants": ["ষোলো", "ষোল", "ষোলোটা"],
        "notes": "Irregular teen",
    },
    {
        "numeric_value": 17,
        "bengali_word": "সতেরো",
        "transliteration": "shotero",
        "english": "seventeen",
        "variants": ["সতেরো", "সতের", "সতেরোটা"],
        "notes": "Irregular teen",
    },
    {
        "numeric_value": 18,
        "bengali_word": "আঠারো",
        "transliteration": "atharo",
        "english": "eighteen",
        "variants": ["আঠারো", "আঠার", "আঠারোটা"],
        "notes": "Irregular teen",
    },
    {
        "numeric_value": 19,
        "bengali_word": "উনিশ",
        "transliteration": "unish",
        "english": "nineteen",
        "variants": ["উনিশ", "ঊনিশ", "উনিশটা"],
        "notes": "Prefix un- (one less than twenty)",
    },
    {
        "numeric_value": 20,
        "bengali_word": "কুড়ি",
        "transliteration": "kuri",
        "english": "twenty (colloquial Kolkata)",
        "variants": ["কুড়ি", "কুড়ি", "বিশ", "কুড়িটা", "বিশটা"],
        "notes": "Colloquial Kolkata prefers 'kuri' (বিশ 'bish' used in compounds)",
    },
    {
        "numeric_value": 29,
        "bengali_word": "ঊনত্রিশ",
        "transliteration": "unotrish",
        "english": "twenty-nine",
        "variants": ["ঊনত্রিশ", "উনত্রিশ"],
        "notes": "Irregular un- prefix (one less than thirty)",
    },
    {
        "numeric_value": 30,
        "bengali_word": "তিরিশ",
        "transliteration": "tirish",
        "english": "thirty",
        "variants": ["তিরিশ", "ত্রিশ", "তিরিশটা"],
        "notes": "Tens value 30 (pronounced tirish in Kolkata)",
    },
    {
        "numeric_value": 39,
        "bengali_word": "ঊনচল্লিশ",
        "transliteration": "unochollish",
        "english": "thirty-nine",
        "variants": ["ঊনচল্লিশ", "উনচল্লিশ"],
        "notes": "Irregular un- prefix (one less than forty)",
    },
    {
        "numeric_value": 40,
        "bengali_word": "চল্লিশ",
        "transliteration": "chollish",
        "english": "forty",
        "variants": ["চল্লিশ", "চল্লিশটা"],
        "notes": "Tens value 40",
    },
    {
        "numeric_value": 49,
        "bengali_word": "ঊনপঞ্চাশ",
        "transliteration": "unoponchash",
        "english": "forty-nine",
        "variants": ["ঊনপঞ্চাশ", "উনপঞ্চাশ"],
        "notes": "Irregular un- prefix (one less than fifty)",
    },
    {
        "numeric_value": 50,
        "bengali_word": "পঞ্চাশ",
        "transliteration": "ponchash",
        "english": "fifty",
        "variants": ["পঞ্চাশ", "পঞ্চাশটা"],
        "notes": "Tens value 50",
    },
    {
        "numeric_value": 59,
        "bengali_word": "ঊনষাট",
        "transliteration": "unoshath",
        "english": "fifty-nine",
        "variants": ["ঊনষাট", "উনষাট"],
        "notes": "Irregular un- prefix (one less than sixty)",
    },
    {
        "numeric_value": 60,
        "bengali_word": "ষাট",
        "transliteration": "shaat",
        "english": "sixty",
        "variants": ["ষাট", "ষাটটা"],
        "notes": "Tens value 60",
    },
    {
        "numeric_value": 69,
        "bengali_word": "ঊনসত্তর",
        "transliteration": "unoshattor",
        "english": "sixty-nine",
        "variants": ["ঊনসত্তর", "উনসত্তর"],
        "notes": "Irregular un- prefix (one less than seventy)",
    },
    {
        "numeric_value": 70,
        "bengali_word": "সত্তর",
        "transliteration": "shottor",
        "english": "seventy",
        "variants": ["সত্তর", "সত্তরটা"],
        "notes": "Tens value 70",
    },
    {
        "numeric_value": 79,
        "bengali_word": "ঊনআশি",
        "transliteration": "unoashi",
        "english": "seventy-nine",
        "variants": ["ঊনআশি", "উনআশি"],
        "notes": "Irregular un- prefix (one less than eighty)",
    },
    {
        "numeric_value": 80,
        "bengali_word": "আশি",
        "transliteration": "ashi",
        "english": "eighty",
        "variants": ["আশি", "আশিটা"],
        "notes": "Tens value 80",
    },
    {
        "numeric_value": 89,
        "bengali_word": "ঊননব্বই",
        "transliteration": "unonobboi",
        "english": "eighty-nine",
        "variants": ["ঊননব্বই", "উননব্বই"],
        "notes": "Irregular un- prefix (one less than ninety)",
    },
    {
        "numeric_value": 90,
        "bengali_word": "নব্বই",
        "transliteration": "nobboi",
        "english": "ninety",
        "variants": ["নব্বই", "নব্বইটা"],
        "notes": "Tens value 90",
    },
    {
        "numeric_value": 100,
        "bengali_word": "একশো",
        "transliteration": "eksho",
        "english": "one hundred",
        "variants": ["একশো", "একশ", "শত", "শো"],
        "notes": "Power of ten (100)",
    },
    {
        "numeric_value": 1000,
        "bengali_word": "হাজার",
        "transliteration": "hajar",
        "english": "one thousand",
        "variants": ["হাজার", "সহস্র"],
        "notes": "Power of ten (1,000)",
    },
    {
        "numeric_value": 100000,
        "bengali_word": "লাখ",
        "transliteration": "lakh",
        "english": "one hundred thousand (1 lakh)",
        "variants": ["লাখ", "লক্ষ"],
        "notes": "South Asian numbering unit (10^5)",
    },
    {
        "numeric_value": 10000000,
        "bengali_word": "কোটি",
        "transliteration": "koti",
        "english": "ten million (1 crore)",
        "variants": ["কোটি", "কোটী"],
        "notes": "South Asian numbering unit (10^7)",
    },
]


# =====================================================================
# Pydantic Schemas for Gemini Structured Output
# =====================================================================
class POSCategory(str, Enum):
    NOUN = "noun"
    VERB = "verb"
    ADJECTIVE = "adjective"
    PRONOUN = "pronoun"
    ADVERB = "adverb"
    POSTPOSITION = "postposition"
    CONJUNCTION = "conjunction"
    INTERJECTION = "interjection"
    PROPER_NOUN = "proper_noun"
    NUMBER = "number"
    NOISE = "noise"


class DialectFlag(str, Enum):
    KOLKATA_STANDARD = "kolkata_standard"
    SADHUBHASHA = "sadhubhasha"
    BANGLADESHI_SPECIFIC = "bangladeshi_specific"
    SLANG_OR_VULGAR = "slang_or_vulgar"


class WordAnnotation(BaseModel):
    surface_word: str = Field(description="The exact input word from the batch.")
    lemma_bengali: str = Field(
        description=(
            "Standard Kolkata (Cholitobhasha) dictionary headword in Bengali script. "
            "Verbs MUST be in their verbal noun dictionary form ending in -আ/-ওয়া/-ানো "
            "(e.g., খাই/খেয়েছি -> খাওয়া, করি/করছে -> করা, যাই/গেলাম -> যাওয়া). "
            "Nouns and pronouns MUST be in nominative singular base form without case "
            "markers or classifiers (e.g., বাড়িতে -> বাড়ি, আমাকে/আমার -> আমি, লোকটা -> লোক)."
        )
    )
    pos: POSCategory = Field(
        description=(
            "Part of speech of the lemma. Use 'proper_noun' for person names, places, "
            "and brand names. Use 'number' ONLY for cardinal numbers (এক, দুই, কুড়ি); "
            "treat ordinal words (প্রথম, দ্বিতীয়) as 'adjective'. Use 'noise' for typos, "
            "non-Bengali Hindi/English words in Bengali script, or broken fragments."
        )
    )
    transliteration: str = Field(
        description=(
            "Phonetic Romanized transliteration of `lemma_bengali` (NOT `surface_word`!) "
            "reflecting colloquial Kolkata pronunciation (e.g., if surface_word is 'করে' and "
            "lemma_bengali is 'করা', transliteration MUST be 'kora', NOT 'kore')."
        )
    )
    english: str = Field(
        description="Concise English dictionary translation (for verbs, use 'to <verb>', e.g., 'to eat / to drink')."
    )
    dialect_flag: DialectFlag = Field(
        description=(
            "'kolkata_standard' if natural in colloquial West Bengal / Kolkata (Cholitobhasha). "
            "'sadhubhasha' if literary/archaic (e.g., করিতেছি, তাহারা, হইয়াছে). "
            "'bangladeshi_specific' if primarily Bangladeshi or Muslim-specific vocabulary (e.g., পানি, সালাম, আপু, খালু, ইনশাআল্লাহ). "
            "'slang_or_vulgar' if profanity or inappropriate slang."
        )
    )
    is_loanword: bool = Field(
        description="True if the word is an English loanword written in Bengali script (e.g., স্কুল, পুলিশ, ফোন, টেবিল, ডাক্তার, স্যার)."
    )


class BatchAnnotationResponse(BaseModel):
    items: list[WordAnnotation]


class LemmaCorrection(BaseModel):
    original_lemma: str = Field(description="The original lemma_bengali being corrected.")
    original_pos: str = Field(description="The original pos of the entry being corrected.")
    corrected_lemma_bengali: str = Field(
        description="Corrected Kolkata Cholitobhasha dictionary headword."
    )
    corrected_pos: POSCategory = Field(description="Corrected part of speech.")
    corrected_transliteration: str = Field(
        description="Corrected Kolkata phonetic Romanization."
    )
    corrected_english: str = Field(description="Corrected English translation.")
    corrected_dialect_flag: DialectFlag = Field(description="Corrected dialect flag.")
    corrected_is_loanword: bool = Field(description="Corrected English loanword flag.")
    reason: str = Field(description="Brief reason for correction.")


class BatchVerificationResponse(BaseModel):
    corrections: list[LemmaCorrection] = Field(
        description="List of ONLY the entries that require corrections. Omit entries that are already accurate."
    )


# =====================================================================
# Stage 1: Download & Pre-Filter
# =====================================================================
def download_frequency_list(url: str = FREQUENCY_LIST_URL, dest_path: str = RAW_FREQ_FILE) -> str:
    """Downloads bn_50k.txt if not already cached locally."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        print(f"[Stage 1] Using cached frequency list at {dest_path}")
        return dest_path

    print(f"[Stage 1] Downloading Bengali frequency list from {url} ...")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(resp.text)
    print(f"[Stage 1] Saved {len(resp.text.splitlines()):,} lines to {dest_path}")
    return dest_path


def normalize_bengali_token(token: str) -> str:
    """Applies Unicode NFC normalization and cleans zero-width artifacts."""
    token = unicodedata.normalize("NFC", token.strip())
    # Strip leading/trailing punctuation or zero-width chars
    token = token.strip("\u200b\u200c\u200d\ufeff")
    return token


def parse_and_prefilter(
    raw_file: str,
    max_raw: int = 12000,
) -> tuple[list[tuple[str, int]], dict[str, int], dict[str, int]]:
    """
    Parses bn_50k.txt, records full raw frequencies for number matching,
    and returns the top `max_raw` clean Bengali word tokens.
    """
    all_raw_counts: dict[str, int] = defaultdict(int)
    clean_candidates: dict[str, int] = defaultdict(int)
    stats = {
        "total_lines": 0,
        "non_bengali_or_punct": 0,
        "pure_digits": 0,
        "stray_fragments": 0,
        "valid_bengali_tokens": 0,
    }

    with open(raw_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                continue
            raw_tok, count_str = parts
            try:
                count = int(count_str)
            except ValueError:
                continue

            stats["total_lines"] += 1
            tok = normalize_bengali_token(raw_tok)
            if not tok:
                continue

            all_raw_counts[tok] += count

            # Pure Bengali digits
            if BENGALI_DIGIT_ONLY_RE.match(tok):
                stats["pure_digits"] += 1
                continue

            # Must consist solely of Bengali Unicode characters
            if not BENGALI_CHAR_RE.match(tok):
                stats["non_bengali_or_punct"] += 1
                continue

            # Must contain at least one Bengali letter and not start with a stray vowel sign
            if not BENGALI_HAS_LETTER_RE.search(tok) or STRAY_DIACRITIC_START_RE.match(tok):
                stats["stray_fragments"] += 1
                continue

            # Reject tokens containing Bengali digits mixed with letters
            if any("\u09E6" <= ch <= "\u09EF" for ch in tok):
                stats["pure_digits"] += 1
                continue

            clean_candidates[tok] += count

    sorted_candidates = sorted(clean_candidates.items(), key=lambda x: x[1], reverse=True)
    stats["valid_bengali_tokens"] = len(sorted_candidates)
    selected = sorted_candidates[:max_raw]

    print(
        f"[Stage 1] Parsed {stats['total_lines']:,} raw lines -> "
        f"{stats['valid_bengali_tokens']:,} valid Bengali tokens "
        f"(filtered {stats['non_bengali_or_punct']:,} non-Bengali/punct, "
        f"{stats['pure_digits']:,} digits, {stats['stray_fragments']:,} fragments). "
        f"Selected top {len(selected):,} tokens."
    )
    return selected, dict(all_raw_counts), stats


# =====================================================================
# Gemini API Caller with Fallback & Rate-Limit Handling
# =====================================================================
def call_gemini_structured(
    client: genai.Client,
    model_name: str,
    system_instruction: str,
    user_prompt: str,
    response_schema: Any,
) -> tuple[Any, str]:
    """Calls Gemini with structured output, thinking_budget=0, model fallback, and retry."""
    candidate_models = [model_name] + [
        m for m in AVAILABLE_MODELS if m != model_name
    ] + ["gemini-2.5-flash", "gemini-2.0-flash"]
    # Deduplicate preserving order
    seen = set()
    models_to_try = [m for m in candidate_models if not (m in seen or seen.add(m))]

    idx = 0
    while True:
        current_model = models_to_try[idx % len(models_to_try)]
        kwargs: dict[str, Any] = dict(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=0.1,
        )
        if "gemini-3" in current_model or "gemini-2.5" in current_model:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

        config = types.GenerateContentConfig(**kwargs)
        try:
            resp = client.models.generate_content(
                model=current_model,
                contents=user_prompt,
                config=config,
            )
            parsed = resp.parsed
            if parsed is None and resp.text:
                parsed = response_schema.model_validate_json(resp.text)
            if parsed is None:
                raise ValueError("Empty structured response from Gemini")
            return parsed, current_model
        except Exception as e:
            err_str = str(e)
            err_type = type(e).__name__
            recoverable = any(
                code in err_str or code in err_type
                for code in (
                    "404",
                    "NOT_FOUND",
                    "503",
                    "UNAVAILABLE",
                    "429",
                    "RESOURCE_EXHAUSTED",
                    "500",
                    "502",
                    "504",
                    "INTERNAL",
                    "ReadError",
                    "ConnectError",
                    "Timeout",
                    "RemoteProtocolError",
                    "Connection",
                    "10053",
                    "10054",
                    "Empty structured response",
                    "ValidationError",
                    "JSONDecodeError",
                )
            )
            if not recoverable:
                raise
            if "404" in err_str or "NOT_FOUND" in err_str:
                idx += 1
                if idx >= len(models_to_try) * 3:
                    raise
                print(
                    f"  [Model Fallback] {current_model} unavailable, trying {models_to_try[idx % len(models_to_try)]}..."
                )
                continue

            wait_s = 5
            m = re.search(r"retry in ([\d\.]+)s", err_str)
            if m:
                wait_s = int(float(m.group(1))) + 1
            print(
                f"  [Transient Error ({err_type}) on {current_model}] Waiting {wait_s}s before retry..."
            )
            time.sleep(wait_s)


# =====================================================================
# Stage 2: Pass 1 - Batched Gemini Lemmatization & Classification
# =====================================================================
PASS1_SYSTEM_PROMPT = """You are an expert Bengali computational linguist specializing in the colloquial Kolkata dialect (Cholitobhasha).
You will be given a JSON list of raw surface Bengali words extracted from subtitle corpora.
For every word in the input list, produce a structured annotation:

1. `surface_word`: The exact surface string provided.
2. `lemma_bengali`: Normalize inflected or conjugated words to their standard Kolkata Cholitobhasha dictionary headword:
   - Verbs MUST be normalized to their verbal noun dictionary form (ending in -আ, -ওয়া, or -ানো), e.g.:
     * করি, করেছ, করবে, করলাম, করছে, করে -> করা (kora - to do)
     * খাই, খেয়েছি, খাবে, খায় -> খাওয়া (khawa - to eat / to drink)
     * যাই, গেলাম, গেছে, যাবে, গিয়ে -> যাওয়া (jawa - to go)
     * আসি, এসেছে, এল, আসবে -> আসা (asha - to come)
     * দিই, দিয়েছে, দেব, দিল -> দেওয়া (dewa - to give)
     * নিই, নিয়েছে, নেব, নিল -> নেওয়া (newa - to take)
     * বলি, বলেছে, বলল, বলবে -> বলা (bola - to say / to speak)
     * দেখি, দেখেছি, দেখল -> দেখা (dekha - to see / to look)
     * আছি, ছিল, থাকবে, থাকে -> থাকা (thaka - to stay / to remain / to exist)
     * হই, হয়েছে, হল, হবে -> হওয়া (howa - to be / to become)
   - Nouns MUST have case suffixes (-র, -ের, -কে, -তে, -য়, -গুলো, -গুলি, -দের) and classifiers (-টা, -টি, -খানা, -জন) stripped to the base singular noun:
     * বাড়িতে, বাড়ির, বাড়িটা -> বাড়ি (bari - house / home)
     * মানুষের, মানুষজন, মানুষটা -> মানুষ (manush - human / person)
     * কথাটা, কথার, কথাগুলো -> কথা (kotha - word / talk)
   - Pronouns MUST be mapped to their nominative base pronoun unless they have a distinct lexicalized dictionary status:
     * আমাকে, আমার, আমায় -> আমি (ami - I)
     * তোমাকে, তোমার, তোমায় -> তুমি (tumi - you [informal])
     * আপনাকে, আপনার -> আপনি (apni - you [formal])
     * তোকে, তোর -> তুই (tui - you [intimate])
     * তাকে, তার, ওকে, ওর -> সে or ও (he/she)
3. `pos`: One of:
   - `noun`, `verb`, `adjective`, `pronoun`, `adverb`, `postposition`, `conjunction`, `interjection`, `proper_noun`, `number`, `noise`.
   - Use `proper_noun` for human names (রাহুল, জন, মেরি), places (কলকাতা, ভারত, লন্ডন), or brands.
   - Use `number` ONLY for cardinal numbers (এক, দুই, তিন, দশ, কুড়ি, হাজার).
   - Ordinal words (প্রথম, দ্বিতীয়, তৃতীয়) MUST be tagged as `adjective`.
   - Use `noise` for misspelled fragments, subtitle gibberish, or untranslated foreign Hindi/Urdu/English words merely transliterated into Bengali script that are not part of Bengali vocabulary.
4. `transliteration`: Phonetic Romanization of `lemma_bengali` (NEVER of the inflected `surface_word`!) matching the Kolkata pronunciation (e.g., when `surface_word` is 'করে' or 'করি' and `lemma_bengali` is 'করা', `transliteration` MUST be 'kora'; when `lemma_bengali` is 'হওয়া', `transliteration` MUST be 'howa'; when `lemma_bengali` is 'থাকা', `transliteration` MUST be 'thaka').
5. `english`: Clear, concise English translation of the dictionary lemma.
6. `dialect_flag`:
   - `kolkata_standard`: Natural in colloquial Kolkata Bengali (Cholitobhasha).
   - `sadhubhasha`: Literary/archaic verb or pronoun forms (e.g., করিতেছি, তাহারা, হইয়াছে, কহিল). If a Sadhubhasha surface form appears, still flag it as `sadhubhasha` so we know the surface token was literary.
   - `bangladeshi_specific`: Words specific to Bangladesh or Muslim-specific register not used in standard Kolkata dialect (e.g., পানি, আসসালামু, সালাম, ইনশাআল্লাহ, আলহামদুলিল্লাহ, খালু, ফুপা, আপু, ভাইয়া).
   - `slang_or_vulgar`: Profanity, swear words, or crude slang.
7. `is_loanword`: `true` if the word is an established English loanword used in Bengali (e.g., স্কুল, কলেজ, পুলিশ, ফোন, টেবিল, ডাক্তার, অফিস, বাস, ট্রেন, স্যার, ম্যাডাম, সরি, থ্যাংকস).
"""


def load_pass1_checkpoint(checkpoint_path: str) -> dict[str, dict[str, Any]]:
    """Loads already-annotated surface words from JSONL checkpoint."""
    annotated: dict[str, dict[str, Any]] = {}
    if not os.path.exists(checkpoint_path):
        return annotated
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                sw = obj.get("surface_word")
                if sw:
                    annotated[sw] = obj
            except json.JSONDecodeError:
                continue
    return annotated


def run_pass1_lemmatization(
    client: genai.Client,
    tokens_with_counts: list[tuple[str, int]],
    model_name: str,
    batch_size: int = 100,
    resume: bool = True,
    checkpoint_path: str = PASS1_CHECKPOINT,
) -> dict[str, dict[str, Any]]:
    """Runs Pass 1 batched Gemini lemmatization with JSONL checkpointing."""
    os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)
    annotated = load_pass1_checkpoint(checkpoint_path) if resume else {}
    if not resume and os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)

    remaining = [tok for tok, _ in tokens_with_counts if tok not in annotated]
    total_batches = (len(remaining) + batch_size - 1) // batch_size

    print(
        f"[Stage 2] Pass 1 Lemmatization: {len(annotated):,} cached in checkpoint, "
        f"{len(remaining):,} tokens remaining across {total_batches} batch(es) (batch_size={batch_size})."
    )

    active_model = model_name
    for b_idx in range(total_batches):
        batch_tokens = remaining[b_idx * batch_size : (b_idx + 1) * batch_size]
        prompt = (
            "Annotate each of the following Bengali surface words into its Kolkata "
            "Cholitobhasha dictionary lemma, POS, transliteration, English translation, "
            "dialect flag, and English loanword status:\n"
            + json.dumps(batch_tokens, ensure_ascii=False)
        )
        t0 = time.perf_counter()
        parsed_resp, active_model = call_gemini_structured(
            client=client,
            model_name=active_model,
            system_instruction=PASS1_SYSTEM_PROMPT,
            user_prompt=prompt,
            response_schema=BatchAnnotationResponse,
        )
        dt = time.perf_counter() - t0

        # Map returned items by surface_word
        returned_map: dict[str, dict[str, Any]] = {}
        for item in parsed_resp.items:
            d = item.model_dump()
            d["pos"] = item.pos.value
            d["dialect_flag"] = item.dialect_flag.value
            returned_map[item.surface_word] = d

        with open(checkpoint_path, "a", encoding="utf-8") as ckpt_f:
            for tok in batch_tokens:
                entry = returned_map.get(tok)
                if entry is None:
                    # Fallback if model slightly normalized surface_word
                    norm_tok = normalize_bengali_token(tok)
                    entry = returned_map.get(norm_tok)
                if entry is None:
                    continue
                entry["surface_word"] = tok
                annotated[tok] = entry
                ckpt_f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        print(
            f"  [Pass 1] Batch {b_idx + 1}/{total_batches} "
            f"({len(returned_map)}/{len(batch_tokens)} words) via {active_model} in {dt:.1f}s"
        )

    return annotated


# =====================================================================
# Stage 3: Aggregate Inflected Forms into Lemmas
# =====================================================================
def aggregate_lemmas(
    tokens_with_counts: list[tuple[str, int]],
    annotations: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """
    Merges surface tokens sharing the same (lemma_bengali, pos) and sums their frequencies.
    Excludes tokens marked as POS == 'noise' or POS == 'number' (numbers are handled in Stage 5).
    """
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    agg_stats = {
        "noise_tokens": 0,
        "number_tokens_routed": 0,
        "unannotated_tokens": 0,
        "merged_surface_tokens": 0,
    }

    # Sort tokens by descending frequency so the highest-frequency surface form's metadata
    # seeds the lemma group first
    for tok, freq in sorted(tokens_with_counts, key=lambda x: x[1], reverse=True):
        ann = annotations.get(tok)
        if not ann:
            agg_stats["unannotated_tokens"] += 1
            continue

        pos = ann.get("pos", "noise")
        if pos == "noise":
            agg_stats["noise_tokens"] += 1
            continue
        if pos == "number":
            agg_stats["number_tokens_routed"] += 1
            continue

        lemma = normalize_bengali_token(ann.get("lemma_bengali", tok)) or tok
        key = (lemma, pos)

        if key not in groups:
            groups[key] = {
                "bengali": lemma,
                "transliteration": ann.get("transliteration", "").strip().lower(),
                "pos": pos,
                "english": ann.get("english", "").strip(),
                "frequency": freq,
                "dialect_flag": ann.get("dialect_flag", "kolkata_standard"),
                "is_loanword": bool(ann.get("is_loanword", False)),
                "merged_forms_count": 1,
                "surface_forms": [tok],
            }
        else:
            g = groups[key]
            g["frequency"] += freq
            g["merged_forms_count"] += 1
            if len(g["surface_forms"]) < 8:
                g["surface_forms"].append(tok)
            # If the canonical lemma itself appeared as a surface token, prefer its
            # direct transliteration and kolkata_standard flag
            if tok == lemma:
                if ann.get("transliteration"):
                    g["transliteration"] = ann["transliteration"].strip().lower()
                if ann.get("dialect_flag") == "kolkata_standard":
                    g["dialect_flag"] = "kolkata_standard"
            if ann.get("is_loanword"):
                g["is_loanword"] = True

        agg_stats["merged_surface_tokens"] += 1

    lemmas = sorted(groups.values(), key=lambda x: x["frequency"], reverse=True)
    print(
        f"[Stage 3] Aggregated {agg_stats['merged_surface_tokens']:,} surface tokens into "
        f"{len(lemmas):,} unique (lemma, POS) entries "
        f"(excluded {agg_stats['noise_tokens']:,} noise tokens, "
        f"routed {agg_stats['number_tokens_routed']:,} number tokens)."
    )
    return lemmas, agg_stats


# =====================================================================
# Stage 4: Pass 2 - Batched Gemini AI Verification Pass (Diff-Only)
# =====================================================================
PASS2_SYSTEM_PROMPT = """You are a senior Bengali lexicographer verifying a master vocabulary table for a Kolkata dialect (Cholitobhasha) language tutor.
Review the provided batch of aggregated Bengali lemma entries.
To minimize output tokens, return ONLY the entries that contain an error in `corrections`. If an entry is already accurate, DO NOT include it in `corrections`.

Check strictly for the following issues:
1. Un-lemmatized forms:
   - Any `verb` whose `bengali` lemma is still conjugated (e.g., করছে, বললাম, যাবে, খাই) instead of its verbal noun dictionary headword (করা, বলা, যাওয়া, খাওয়া).
   - Any `noun` or `pronoun` that still has case endings or classifiers attached (e.g., বাড়িতে -> বাড়ি, মানুষের -> মানুষ, আমাকে -> আমি).
2. Dialect & Register accuracy (`dialect_flag`):
   - Flag any literary/archaic Sadhubhasha headwords as `sadhubhasha`.
   - Flag any Bangladeshi or Muslim-specific words not standard in colloquial Kolkata (e.g., পানি, সালাম, আপু, খালু, ইনশাআল্লাহ) as `bangladeshi_specific`.
   - Flag any profanity/vulgarity as `slang_or_vulgar`.
   - Flag non-Bengali noise/fragments as ` corrected_pos = "noise" `.
3. POS accuracy:
   - Personal names, cities, countries, and brands MUST be `proper_noun`.
   - Cardinal numbers MUST be `number`; ordinal numbers (প্রথম, দ্বিতীয়) MUST be `adjective`.
4. Transliteration & English translation:
   - Ensure `transliteration` reflects Kolkata pronunciation and `english` is an accurate dictionary gloss.
"""


def load_pass2_checkpoint(checkpoint_path: str) -> set[int]:
    """Loads already-verified batch indices from Pass 2 checkpoint."""
    done: set[int] = set()
    if not os.path.exists(checkpoint_path):
        return done
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "batch_idx" in obj:
                    done.add(int(obj["batch_idx"]))
            except (json.JSONDecodeError, ValueError):
                continue
    return done


def load_pass2_corrections_from_checkpoint(checkpoint_path: str) -> list[dict[str, Any]]:
    """Loads saved corrections from Pass 2 checkpoint."""
    corrs: list[dict[str, Any]] = []
    if not os.path.exists(checkpoint_path):
        return corrs
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                corrs.extend(obj.get("corrections", []))
            except json.JSONDecodeError:
                continue
    return corrs


def run_pass2_verification(
    client: genai.Client,
    lemmas: list[dict[str, Any]],
    model_name: str,
    batch_size: int = 100,
    resume: bool = True,
    checkpoint_path: str = PASS2_CHECKPOINT,
) -> list[dict[str, Any]]:
    """
    Runs a diff-only Gemini verification pass over the aggregated lemmas,
    applies corrections, and re-merges any lemmas that collapsed together.
    """
    os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)
    if not resume and os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)

    done_batches = load_pass2_checkpoint(checkpoint_path) if resume else set()
    total_batches = (len(lemmas) + batch_size - 1) // batch_size
    print(
        f"[Stage 4] Pass 2 AI Verification: Auditing {len(lemmas):,} unique lemmas "
        f"across {total_batches} batch(es) ({len(done_batches)} cached, diff-only output)..."
    )

    active_model = model_name

    for b_idx in range(total_batches):
        if b_idx in done_batches:
            continue
        batch = lemmas[b_idx * batch_size : (b_idx + 1) * batch_size]
        payload = [
            {
                "bengali": item["bengali"],
                "pos": item["pos"],
                "transliteration": item["transliteration"],
                "english": item["english"],
                "dialect_flag": item["dialect_flag"],
                "is_loanword": item["is_loanword"],
            }
            for item in batch
        ]
        prompt = (
            "Audit these Bengali dictionary entries and return ONLY the ones needing corrections:\n"
            + json.dumps(payload, ensure_ascii=False)
        )

        t0 = time.perf_counter()
        parsed_resp, active_model = call_gemini_structured(
            client=client,
            model_name=active_model,
            system_instruction=PASS2_SYSTEM_PROMPT,
            user_prompt=prompt,
            response_schema=BatchVerificationResponse,
        )
        dt = time.perf_counter() - t0

        serialized_corrs = []
        for c in parsed_resp.corrections:
            d = c.model_dump()
            d["corrected_pos"] = c.corrected_pos.value
            d["corrected_dialect_flag"] = c.corrected_dialect_flag.value
            serialized_corrs.append(d)

        with open(checkpoint_path, "a", encoding="utf-8") as ckpt_f:
            ckpt_f.write(
                json.dumps(
                    {"batch_idx": b_idx, "corrections": serialized_corrs},
                    ensure_ascii=False,
                )
                + "\n"
            )

        print(
            f"  [Pass 2] Batch {b_idx + 1}/{total_batches}: "
            f"{len(serialized_corrs)} correction(s) found via {active_model} in {dt:.1f}s"
        )

    all_corrs = load_pass2_corrections_from_checkpoint(checkpoint_path)
    corr_map: dict[tuple[str, str], dict[str, Any]] = {
        (normalize_bengali_token(c["original_lemma"]), c["original_pos"]): c
        for c in all_corrs
    }

    corrections_applied = 0
    for item in lemmas:
        key = (item["bengali"], item["pos"])
        corr = corr_map.get(key)
        if corr:
            item["bengali"] = (
                normalize_bengali_token(corr["corrected_lemma_bengali"]) or item["bengali"]
            )
            item["pos"] = corr["corrected_pos"]
            item["transliteration"] = corr["corrected_transliteration"].strip().lower()
            item["english"] = corr["corrected_english"].strip()
            item["dialect_flag"] = corr["corrected_dialect_flag"]
            item["is_loanword"] = bool(corr["corrected_is_loanword"])
            corrections_applied += 1

    noise_removed_in_pass2 = 0
    # Re-merge in case Pass 2 corrected an inflected form into an existing lemma
    merged_after_verify: dict[tuple[str, str], dict[str, Any]] = {}
    for item in lemmas:
        if item["pos"] in ("noise", "number"):
            if item["pos"] == "noise":
                noise_removed_in_pass2 += 1
            continue
        key = (item["bengali"], item["pos"])
        if key not in merged_after_verify:
            merged_after_verify[key] = dict(item)
        else:
            existing = merged_after_verify[key]
            existing["frequency"] += item["frequency"]
            existing["merged_forms_count"] += item["merged_forms_count"]

    final_lemmas = sorted(
        merged_after_verify.values(), key=lambda x: x["frequency"], reverse=True
    )
    print(
        f"[Stage 4] Verification complete: {corrections_applied:,} correction(s) applied, "
        f"{noise_removed_in_pass2:,} additional noise entries removed, "
        f"{len(final_lemmas):,} verified lemmas remaining."
    )
    return final_lemmas


# =====================================================================
# Stage 5: Smart Bengali Numbers Table
# =====================================================================
def build_numbers_table(all_raw_counts: dict[str, int]) -> list[dict[str, Any]]:
    """
    Constructs the curated Bengali numbers table (0-19, irregular un- compounds,
    tens 20-90, and powers of 10) with matched frequencies from the raw corpus.
    """
    rows: list[dict[str, Any]] = []
    for idx, spec in enumerate(CURATED_NUMBERS, start=1):
        num_val = spec["numeric_value"]
        bn_numeral = to_bengali_numeral(num_val)
        freq = all_raw_counts.get(bn_numeral, 0) + all_raw_counts.get(str(num_val), 0)
        for var in spec.get("variants", []):
            norm_var = normalize_bengali_token(var)
            freq += all_raw_counts.get(norm_var, 0)

        rows.append(
            {
                "id": f"num_{idx:04d}",
                "numeric_value": num_val,
                "bengali_numeral": bn_numeral,
                "bengali_word": spec["bengali_word"],
                "transliteration": spec["transliteration"],
                "english": spec["english"],
                "frequency": freq,
                "notes": spec["notes"],
            }
        )

    print(f"[Stage 5] Built smart Bengali numbers table with {len(rows)} curated entries.")
    return rows


# =====================================================================
# Interactive Overwrite Protection Helper
# =====================================================================
def resolve_output_path(
    target_path: str,
    is_directory: bool = False,
    non_interactive_mode: str | None = None,
) -> str | None:
    """
    Checks if `target_path` already exists (or contains files if a directory).
    If so, prompts the user whether to Replace, choose a New name, or Cancel.
    Never quietly overwrites existing files.
    """
    exists = (
        os.path.isdir(target_path) and bool(os.listdir(target_path))
        if is_directory
        else os.path.exists(target_path)
    )
    if not exists:
        return target_path

    if non_interactive_mode == "replace":
        print(f"[Overwrite Protection] Replacing existing target: {target_path}")
        return target_path

    kind = "Directory" if is_directory else "File"
    print(f"\n[Overwrite Protection] {kind} already exists: {target_path}")
    while True:
        try:
            choice = (
                input(
                    f"Do you want to [R]eplace '{target_path}', enter a [N]ew name, or [C]ancel? (r/n/c): "
                )
                .strip()
                .lower()
            )
        except EOFError:
            print("No interactive stdin detected; cancelling overwrite to stay safe.")
            return None

        if choice in ("r", "replace"):
            return target_path
        if choice in ("n", "new"):
            new_path = input(f"Enter new path for {kind.lower()}: ").strip()
            if new_path:
                return resolve_output_path(new_path, is_directory=is_directory)
        if choice in ("c", "cancel"):
            print(f"Skipped writing {target_path}.")
            return None


# =====================================================================
# Stage 6 & 7: Export Master CSVs and Per-POS Curriculum JSON Files
# =====================================================================
POS_ID_PREFIX = {
    "noun": "noun",
    "verb": "verb",
    "adjective": "adj",
    "pronoun": "pron",
    "adverb": "adv",
    "postposition": "post",
    "conjunction": "conj",
    "interjection": "intj",
    "proper_noun": "prop",
    "number": "num",
}

POS_FILENAME_MAP = {
    "noun": "nouns.json",
    "verb": "verbs.json",
    "adjective": "adjectives.json",
    "pronoun": "pronouns.json",
    "adverb": "adverbs.json",
    "postposition": "postpositions.json",
    "conjunction": "conjunctions.json",
    "interjection": "interjections.json",
}


def load_master_vocab_csv(csv_path: str) -> list[dict[str, Any]]:
    """Loads existing master_vocabulary.csv without re-running API calls."""
    rows: list[dict[str, Any]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(
                {
                    "bengali": r["bengali"],
                    "transliteration": r["transliteration"],
                    "pos": r["pos"],
                    "english": r["english"],
                    "frequency": int(r["frequency"]),
                    "dialect_flag": r["dialect_flag"],
                    "is_loanword": str(r.get("is_loanword", "")).lower() == "true",
                    "merged_forms_count": int(r.get("merged_forms_count", 1) or 1),
                }
            )
    return rows


def load_master_numbers_csv(csv_path: str) -> list[dict[str, Any]]:
    """Loads existing master_numbers.csv without re-running corpus scan."""
    rows: list[dict[str, Any]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(
                {
                    "id": r["id"],
                    "numeric_value": int(r["numeric_value"]),
                    "bengali_numeral": r["bengali_numeral"],
                    "bengali_word": r["bengali_word"],
                    "transliteration": r["transliteration"],
                    "english": r["english"],
                    "frequency": int(r["frequency"]),
                    "notes": r.get("notes", ""),
                }
            )
    return rows


def write_master_vocab_csv(
    lemmas: list[dict[str, Any]],
    csv_path: str,
    non_interactive_mode: str | None = None,
) -> str | None:
    resolved = resolve_output_path(
        csv_path, is_directory=False, non_interactive_mode=non_interactive_mode
    )
    if not resolved:
        return None
    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    fieldnames = [
        "bengali",
        "transliteration",
        "pos",
        "english",
        "frequency",
        "dialect_flag",
        "is_loanword",
        "merged_forms_count",
    ]
    with open(resolved, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in lemmas:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    print(f"[Stage 6] Wrote {len(lemmas):,} rows to master vocabulary CSV: {resolved}")
    return resolved


def write_master_numbers_csv(
    numbers_rows: list[dict[str, Any]],
    csv_path: str,
    non_interactive_mode: str | None = None,
) -> str | None:
    resolved = resolve_output_path(
        csv_path, is_directory=False, non_interactive_mode=non_interactive_mode
    )
    if not resolved:
        return None
    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    fieldnames = [
        "id",
        "numeric_value",
        "bengali_numeral",
        "bengali_word",
        "transliteration",
        "english",
        "frequency",
        "notes",
    ]
    with open(resolved, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in numbers_rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    print(f"[Stage 6] Wrote {len(numbers_rows):,} rows to master numbers CSV: {resolved}")
    return resolved


def compile_curriculum_jsons(
    lemmas: list[dict[str, Any]],
    numbers_rows: list[dict[str, Any]],
    output_dir: str,
    top_k: int = 5000,
    non_interactive_mode: str | None = None,
) -> tuple[str | None, dict[str, list[dict[str, Any]]]]:
    """
    Filters master lemmas to `kolkata_standard`, selects the top `top_k` most
    frequent words, assigns unique deterministic IDs per POS, and writes
    separate JSON files per POS plus `numbers.json`.
    """
    resolved_dir = resolve_output_path(
        output_dir, is_directory=True, non_interactive_mode=non_interactive_mode
    )
    if not resolved_dir:
        return None, {}

    os.makedirs(resolved_dir, exist_ok=True)

    # Filter out non-Kolkata / Sadhubhasha / vulgar words and proper nouns
    kolkata_lemmas = [
        item
        for item in lemmas
        if item.get("dialect_flag") == "kolkata_standard"
        and item.get("pos") != "proper_noun"
    ]
    kolkata_lemmas.sort(key=lambda x: x["frequency"], reverse=True)
    selected_lemmas = kolkata_lemmas[:top_k]

    # Remove deprecated proper_nouns.json if present from an older run
    legacy_proper_nouns_path = os.path.join(resolved_dir, "proper_nouns.json")
    if os.path.exists(legacy_proper_nouns_path):
        os.remove(legacy_proper_nouns_path)

    pos_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in selected_lemmas:
        pos = item["pos"]
        pos_buckets[pos].append(item)

    compiled_by_pos: dict[str, list[dict[str, Any]]] = {}

    for pos, filename in POS_FILENAME_MAP.items():
        bucket = sorted(pos_buckets.get(pos, []), key=lambda x: x["frequency"], reverse=True)
        prefix = POS_ID_PREFIX.get(pos, pos[:4])
        records: list[dict[str, Any]] = []
        for idx, entry in enumerate(bucket, start=1):
            records.append(
                {
                    "id": f"{prefix}_{idx:04d}",
                    "bengali": entry["bengali"],
                    "transliteration": entry["transliteration"],
                    "english": entry["english"],
                    "pos": pos,
                    "frequency": entry["frequency"],
                    "is_loanword": bool(entry.get("is_loanword", False)),
                }
            )
        compiled_by_pos[pos] = records
        file_path = os.path.join(resolved_dir, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

    # Write numbers.json sorted by descending frequency (while keeping numeric_value metadata)
    sorted_numbers = sorted(
        numbers_rows, key=lambda x: (-x["frequency"], x["numeric_value"])
    )
    number_records: list[dict[str, Any]] = []
    for idx, nrow in enumerate(sorted_numbers, start=1):
        number_records.append(
            {
                "id": f"num_{idx:04d}",
                "numeric_value": nrow["numeric_value"],
                "bengali_numeral": nrow["bengali_numeral"],
                "bengali": nrow["bengali_word"],
                "transliteration": nrow["transliteration"],
                "english": nrow["english"],
                "pos": "number",
                "frequency": nrow["frequency"],
                "notes": nrow["notes"],
                "is_loanword": False,
            }
        )
    compiled_by_pos["number"] = number_records
    numbers_json_path = os.path.join(resolved_dir, "numbers.json")
    with open(numbers_json_path, "w", encoding="utf-8") as f:
        json.dump(number_records, f, ensure_ascii=False, indent=2)

    print(
        f"[Stage 7] Compiled {len(selected_lemmas):,} Kolkata-standard words + "
        f"{len(number_records)} numbers into per-POS JSON files in: {resolved_dir}"
    )
    return resolved_dir, compiled_by_pos


# =====================================================================
# Stage 8: Summary Report
# =====================================================================
def print_pipeline_summary(
    prefilter_stats: dict[str, int],
    agg_stats: dict[str, int],
    lemmas: list[dict[str, Any]],
    compiled_by_pos: dict[str, list[dict[str, Any]]],
):
    dialect_counts: dict[str, int] = defaultdict(int)
    master_pos_counts: dict[str, int] = defaultdict(int)
    loanword_count = 0

    for item in lemmas:
        dialect_counts[item.get("dialect_flag", "unknown")] += 1
        master_pos_counts[item.get("pos", "unknown")] += 1
        if item.get("is_loanword"):
            loanword_count += 1

    print("\n=====================================================================")
    print(" Bengali Vocabulary Pipeline Summary")
    print("=====================================================================")
    print(f"Raw Corpus Lines Read:          {prefilter_stats.get('total_lines', 0):,}")
    print(f"Valid Bengali Word Tokens:      {prefilter_stats.get('valid_bengali_tokens', 0):,}")
    print(f"Surface Tokens Processed:       {agg_stats.get('merged_surface_tokens', 0):,}")
    print(f"Noise Tokens Discarded:         {agg_stats.get('noise_tokens', 0):,}")
    print(f"Unique Verified Lemmas (CSV):   {len(lemmas):,}")
    if lemmas:
        pct_loan = (loanword_count / len(lemmas)) * 100
        print(f"English Loanwords Identified:   {loanword_count:,} ({pct_loan:.1f}%)")

    print("\n--- Dialect / Register Breakdown (Master CSV) ---")
    for d_flag, cnt in sorted(dialect_counts.items(), key=lambda x: x[1], reverse=True):
        pct = (cnt / len(lemmas) * 100) if lemmas else 0.0
        print(f"  {d_flag:<24} : {cnt:>6,} ({pct:5.1f}%)")

    print("\n--- Master CSV Breakdown by Part of Speech ---")
    for pos, cnt in sorted(master_pos_counts.items(), key=lambda x: x[1], reverse=True):
        pct = (cnt / len(lemmas) * 100) if lemmas else 0.0
        print(f"  {pos:<24} : {cnt:>6,} ({pct:5.1f}%)")

    if compiled_by_pos:
        total_curriculum = sum(
            len(items) for pos, items in compiled_by_pos.items() if pos != "number"
        )
        print(f"\n--- Compiled Learning Curriculum JSONs ({total_curriculum:,} words + numbers) ---")
        for pos, items in sorted(
            compiled_by_pos.items(), key=lambda x: len(x[1]), reverse=True
        ):
            examples = ", ".join(
                f"{it['bengali']} ({it['transliteration']})" for it in items[:3]
            )
            print(f"  {pos:<16} : {len(items):>5,} entries | Top: {examples}")

    print("=====================================================================\n")


# =====================================================================
# CLI Entrypoint
# =====================================================================
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build standardized Kolkata Bengali master vocabulary CSV and per-POS curriculum JSON files."
    )
    parser.add_argument(
        "--max-raw",
        type=int,
        default=12000,
        help="Number of top raw Bengali tokens from bn_50k.txt to process (default: 12000).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5000,
        help="Number of most frequent Kolkata-standard words to include in curriculum JSONs (default: 5000).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=125,
        help="Number of words per Gemini API batch call (default: 125).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=PRIMARY_MODEL,
        help=f"Primary Gemini model to use (default: {PRIMARY_MODEL}).",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore existing Pass 1 checkpoints and re-run all API batches from scratch.",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip Pass 2 Gemini AI verification pass.",
    )
    parser.add_argument(
        "--master-csv",
        type=str,
        default=DEFAULT_MASTER_VOCAB_CSV,
        help=f"Output path for master vocabulary CSV (default: {DEFAULT_MASTER_VOCAB_CSV}).",
    )
    parser.add_argument(
        "--numbers-csv",
        type=str,
        default=DEFAULT_MASTER_NUMBERS_CSV,
        help=f"Output path for master numbers CSV (default: {DEFAULT_MASTER_NUMBERS_CSV}).",
    )
    parser.add_argument(
        "--vocab-dir",
        type=str,
        default=DEFAULT_VOCAB_JSON_DIR,
        help=f"Output directory for per-POS curriculum JSONs (default: {DEFAULT_VOCAB_JSON_DIR}).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Automatically replace existing output files without interactive prompt.",
    )
    parser.add_argument(
        "--compile-only",
        action="store_true",
        help="Compile per-POS curriculum JSONs directly from existing master CSVs without touching master CSVs or calling the Gemini API.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    non_interactive_mode = "replace" if args.overwrite else None

    if args.compile_only:
        if not os.path.exists(args.master_csv) or not os.path.exists(args.numbers_csv):
            print(
                f"Error: --compile-only requires existing {args.master_csv} and {args.numbers_csv}."
            )
            sys.exit(1)
        lemmas = load_master_vocab_csv(args.master_csv)
        numbers_rows = load_master_numbers_csv(args.numbers_csv)
        _, compiled_by_pos = compile_curriculum_jsons(
            lemmas=lemmas,
            numbers_rows=numbers_rows,
            output_dir=args.vocab_dir,
            top_k=args.top_k,
            non_interactive_mode=non_interactive_mode,
        )
        print_pipeline_summary(
            prefilter_stats={},
            agg_stats={},
            lemmas=lemmas,
            compiled_by_pos=compiled_by_pos,
        )
        return

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        try:
            api_key = input("Enter your Google API Key: ").strip()
        except EOFError:
            print("Error: GOOGLE_API_KEY environment variable is not set.")
            sys.exit(1)
        os.environ["GOOGLE_API_KEY"] = api_key

    client = genai.Client(api_key=api_key)
    non_interactive_mode = "replace" if args.overwrite else None

    # Stage 1: Download & Pre-filter
    raw_path = download_frequency_list()
    selected_tokens, all_raw_counts, prefilter_stats = parse_and_prefilter(
        raw_path, max_raw=args.max_raw
    )

    # Stage 2: Pass 1 Batched Lemmatization
    annotations = run_pass1_lemmatization(
        client=client,
        tokens_with_counts=selected_tokens,
        model_name=args.model,
        batch_size=args.batch_size,
        resume=not args.no_resume,
    )

    # Stage 3: Aggregate Lemmas
    lemmas, agg_stats = aggregate_lemmas(selected_tokens, annotations)

    # Stage 4: Pass 2 AI Verification Pass
    if not args.skip_verify and lemmas:
        lemmas = run_pass2_verification(
            client=client,
            lemmas=lemmas,
            model_name=args.model,
            batch_size=args.batch_size,
            resume=not args.no_resume,
        )

    # Stage 5: Smart Bengali Numbers Table
    numbers_rows = build_numbers_table(all_raw_counts)

    # Stage 6: Write Master CSVs
    write_master_vocab_csv(
        lemmas, args.master_csv, non_interactive_mode=non_interactive_mode
    )
    write_master_numbers_csv(
        numbers_rows, args.numbers_csv, non_interactive_mode=non_interactive_mode
    )

    # Stage 7: Compile Per-POS Curriculum JSONs
    _, compiled_by_pos = compile_curriculum_jsons(
        lemmas=lemmas,
        numbers_rows=numbers_rows,
        output_dir=args.vocab_dir,
        top_k=args.top_k,
        non_interactive_mode=non_interactive_mode,
    )

    # Stage 8: Summary Report
    print_pipeline_summary(
        prefilter_stats=prefilter_stats,
        agg_stats=agg_stats,
        lemmas=lemmas,
        compiled_by_pos=compiled_by_pos,
    )


if __name__ == "__main__":
    main()
