# Bangla Bot: Kolkata Dialect Tutor 🇮🇳

> **Note:** This project was created with the assistance of Gemini, partly as a way to experiment with agent-assisted coding techniques.

An interactive, programmatic Bengali language learning environment focused on the Kolkata dialect. This project uses the Gemini API to generate contextual practice sessions, track progress, and provide real-time audio feedback.

## Features

-   **Structured Learning:** Vocabulary and grammar concepts are tracked in `progress.json` with mastery scores.
-   **Contextual Practice:** Gemini generates sentences based on your weakest areas, ensuring efficient learning.
-   **Audio Feedback:** Automated Text-to-Speech (TTS) using `gTTS` to help with pronunciation.
-   **GUI & CLI:** Choose between a graphical interface or a terminal environment.
-   **Progress Analytics:** A dedicated summary script to visualize your learning journey.
-   **Dialect Specific:** Explicitly configured for the Kolkata dialect (e.g., preferring "Jol" over "Pani").

## Project Structure

-   `gui_practice.py`: The main Flet-based graphical interface.
-   `practice.py`: Terminal-based practice environment.
-   `summary.py`: Generates statistics and identifies areas for improvement.
-   `reset_progress.py`: Resets mastery scores and encounter counts in `progress.json`.
-   `progress.json`: The database tracking your vocabulary and grammar mastery.
-   `curriculum/`: Stable vocabulary (`vocabulary.json`) and grammar (`grammar.json`) curriculum files.
-   `GEMINI.md`: Instructions and rules for the AI tutor.
-   `pyproject.toml` & `uv.lock`: Cross-platform dependency and environment configuration managed by [`uv`](https://docs.astral.sh/uv/).

## Setup & Installation

This project uses **[`uv`](https://docs.astral.sh/uv/)** for fast, cross-platform Python environment and dependency management.

### 1. Install `uv` (if not already installed)

-   **Windows (PowerShell)**:
    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```
-   **Linux / macOS / WSL**:
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```
    *(On Linux/WSL, also install `mpg123` if you plan to use the CLI audio playback: `sudo apt install -y mpg123`)*

### 2. Sync the Environment

From the project directory on any platform, run:

```bash
uv sync
```

*(On Windows, you can also run `.\setup_windows.ps1`, which installs `uv` if needed and runs `uv sync`.)*

## API Key Configuration

This project requires a Google Gemini API key from [Google AI Studio](https://aistudio.google.com/).

-   **Windows (Permanent)**:
    ```powershell
    [System.Environment]::SetEnvironmentVariable('GOOGLE_API_KEY', 'your-key-here', 'User')
    ```
-   **Linux / macOS / WSL**:
    ```bash
    export GOOGLE_API_KEY="your_api_key_here"
    ```

## How to Use

### Start the GUI
```bash
uv run python gui_practice.py
```
*(Or use `.\launch_windows.ps1` on Windows / `./launch.sh` on Linux/WSL.)*

### Start the CLI Practice
```bash
uv run python practice.py
```

### View Progress Summary
```bash
uv run python summary.py
```

### Reset Progress
```bash
uv run python reset_progress.py
```
