# Bangla Bot: Kolkata Dialect (Cholitobhasha) Tutor

> **Note:** This project was created with the assistance of Gemini, partly as a way to experiment with agent-assisted coding techniques.

**Bangla Bot** is an interactive Bengali language tutor built around the **colloquial Kolkata dialect (`Cholitobhasha`)**. It pairs a frequency-ranked **5,039-word curriculum** derived from OpenSubtitles Bengali corpora, a **5-level Spaced Repetition System (SRS)**, multi-mode Gemini AI tutoring sessions, and automated `gTTS` audio playback across both a desktop GUI (`Flet`) and a terminal CLI.

---

## Overview for New Users

Bangla Bot is designed for native English speakers learning spoken Kolkata Bengali from the ground up:

1. **Launch the app** (GUI or CLI) to view your **Main Dashboard** showing total vocabulary/grammar learned, items due for review today, and your 5-level SRS breakdown.
2. **Start with a Learning Session** (default: 5 new words, 5 review words, 2 grammar concepts):
   - **Phase 1 — Introduction:** The tutor introduces only the new words and grammar concepts (highlighting English loanwords and Bengali numerals), while holding back review items.
   - **Phase 2 — Bidirectional Translation Drills:** Practice translating one sentence at a time between English and Bangla across both new and review items. Mistakes receive targeted hints without spoiling the answer.
   - **Phase 3 — Bangla Practice Conversation:** Wrap up with a short, natural Bangla conversation covering every item in the session, with English coaching as needed.
   - **Phase 4 — Automated SRS Scoring:** At the end of the session (or anytime you click **Finish & Score** / type `finish`), the tutor evaluates each item and updates `progress.json` through a dedicated helper tool.
3. **Reinforce & Explore:**
   - Use **Review Sessions** to drill due and weakest learned items without re-introductions.
   - Use **Conversation Sessions** to jump straight into interactive Bangla dialogue using your learned vocabulary.
   - Use the **Vocabulary Browser** to search, filter, sort, and hear pronunciations across all 5,039 words, or use **Custom Sessions** to hand-pick specific words and grammar concepts.

---

## Key Features

- **5,039-Word Kolkata (`Cholitobhasha`) Curriculum:**
  - `5,000` general vocabulary lemmas split across 8 Parts of Speech (`nouns`, `verbs`, `adjectives`, `adverbs`, `pronouns`, `postpositions`, `conjunctions`, `interjections`), sorted by descending corpus frequency and tagged with English loanword indicators (`is_loanword`).
  - `39` curated cardinal numbers (`0–19`, irregular `ঊন-` forms, tens `20–90`, and South Asian units like `লাখ`/`কোটি`) including both Bengali numerals (`০–৯`) and Kolkata pronunciations.
  - `5` foundational grammar concepts (`gram_0001`–`gram_0005`).
  - Non-Kolkata dialectal terms (such as Bangladeshi-specific vocabulary or literary `Sadhubhasha` forms) are filtered out of the active learning files by `build_vocabulary.py`.
- **5-Level Spaced Repetition System (`progress.json` v2):**
  - Schedule intervals: **Level 1** (`1 day`), **Level 2** (`3 days`), **Level 3** (`7 days`), **Level 4** (`14 days`), **Level 5** (`30 days`).
  - Newly introduced items always start locked at **Level 1** after their introductory session so every word gets at least one spaced review before advancing.
  - Review items advance (`promote`: `+1`, max `5`), remain (`stay`), or step back (`demote`: `-1`, min `1`) based on recall.
  - Review selection prioritizes items past `next_review_due`, backfilling from the lowest-level and least-recently-practiced learned items so you can practice multiple times a day.
- **POS-Balanced Word Introduction:** New words follow corpus frequency while balancing across Parts of Speech (anchoring verbs, nominals, and modifiers) so early sessions immediately support real sentences.
- **Filterable Vocabulary Browser:** Search by Bengali script, transliteration, English gloss, or ID; filter by Part of Speech, SRS status (`Unseen`, `Encountered`, `Due`, `Level 1`–`Level 5`), or origin (`Native` vs. `English Loanword`); view `First Encountered` and `Last Practiced` dates; and click any word to play pronunciation audio.
- **Real-Time Audio (`gTTS`):** Bengali phrases wrapped in `<audio>...</audio>` tags are prefetched and cached in memory for instant playback.

---

## Setup & Installation

This project uses **[`uv`](https://docs.astral.sh/uv/)** for cross-platform Python (`>=3.12`) dependency management.

### 1. Install `uv` (if not already installed)

- **Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **Linux / macOS / WSL:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
  *(On Linux/WSL, install `mpg123` for CLI audio playback: `sudo apt install -y mpg123`)*

### 2. Sync Dependencies

```bash
uv sync
```
*(On Windows, you can alternatively run `.\setup_windows.ps1`.)*

### 3. Configure Your Gemini API Key

Obtain a key from [Google AI Studio](https://aistudio.google.com/) and set `GOOGLE_API_KEY`:

- **Windows (Permanent):**
  ```powershell
  [System.Environment]::SetEnvironmentVariable('GOOGLE_API_KEY', 'your-key-here', 'User')
  ```
- **Linux / macOS / WSL:**
  ```bash
  export GOOGLE_API_KEY="your_api_key_here"
  ```
  *(In the Flet GUI, you can also paste your API key directly into the dashboard banner for the current session if the environment variable is not set.)*

---

## How to Use

### Start the Desktop GUI (Recommended)
```bash
uv run python gui_practice.py
```
- **Windows shortcut:** `.\launch_windows.ps1` (also falls back to `.\.venv\Scripts\python.exe` if `uv` is not on `PATH`)
- **Linux / WSL shortcut:** `./launch.sh`

### Start the Terminal CLI
```bash
uv run python practice.py
```
During a CLI session, type `r` / `repeat` to replay the last audio, `finish` to wrap up and trigger SRS scoring, or `menu` / `quit` to return to the menu.

### View Progress Summary
```bash
uv run python summary.py
```

### Reset Progress
```bash
uv run python reset_progress.py
```

### Recompile Vocabulary JSONs (Offline) or Rebuild Corpus
To adjust the top-K curriculum slice (default `5,000`) directly from `data/master_vocabulary.csv` without making Gemini API calls:
```bash
uv run python build_vocabulary.py --compile-only --top-k 5000
```
*(Running `build_vocabulary.py` without `--compile-only` re-runs the full OpenSubtitles download, batched Gemini lemmatization, and verification pipeline.)*

### Run Automated Tests
```bash
uv run python -m unittest discover -s tests -v
```

---

## Project Structure

- `gui_practice.py` — Multi-view Flet desktop application (Main Dashboard, Vocabulary Browser, Custom Session Picker, Active Chat Session).
- `practice.py` — Interactive terminal CLI menu and practice loop.
- `curriculum_manager.py` — Loads per-POS vocabulary JSONs and `grammar.json`; implements POS-balanced new selection, due+backfill review selection, and browser queries.
- `progress_manager.py` — Manages `progress.json` (schema v2) and 5-level SRS scheduling/transitions.
- `session_builder.py` — Builds `SessionPlan` objects, constructs mode-specific system prompts, and exposes the session-scoped `submit_session_scores` tool.
- `tutor_core.py` — Gemini `GenerateContentConfig` builder, model fallback list, `<audio>` tag parsing, and `gTTS` caching/playback.
- `summary.py` & `reset_progress.py` — CLI progress summary and v2 progress reset utilities.
- `build_vocabulary.py` — Offline/Gemini pipeline that generated the master CSVs and per-POS curriculum files from `bn_50k.txt`.
- `prompts/tutor_base.md` — Shared Kolkata (`Cholitobhasha`) pedagogical rules injected into tutor sessions.
- `curriculum/vocabulary/*.json` — Per-POS JSON curriculum files (`nouns.json`, `verbs.json`, `adjectives.json`, `adverbs.json`, `pronouns.json`, `postpositions.json`, `conjunctions.json`, `interjections.json`, `numbers.json`).
- `curriculum/grammar.json` — Grammar concepts (`gram_0001`–`gram_0005`).
- `data/master_vocabulary.csv` & `data/master_numbers.csv` — Verified master frequency tables generated by `build_vocabulary.py`.
- `progress.json` — Local learner SRS state (gitignored).
- `tests/test_srs_and_selection.py` — Automated unit tests for SRS rules, POS balancing, selection ordering, filtering, and UI smoke checks.
- `GEMINI.md` — Developer architecture reference.
- `pyproject.toml` & `uv.lock` — Project dependencies managed by `uv`.
