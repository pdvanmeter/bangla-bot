# Bangla Bot: Kolkata Dialect Tutor 🇮🇳

> **Note:** This project was created with the assistance of Gemini, partly as a way to experiment with agent-assisted coding techniques.

An interactive, programmatic Bengali language learning environment focused on the Kolkata dialect. This project uses the Gemini API to generate contextual practice sessions, track progress, and provide real-time audio feedback.

## Features

-   **Structured Learning:** Vocabulary and grammar concepts are tracked in `progress.json` with mastery scores.
-   **Contextual Practice:** Gemini generates sentences based on your weakest areas, ensuring efficient learning.
-   **Audio Feedback:** Automated Text-to-Speech (TTS) using `gTTS` to help with pronunciation.
-   **Progress Analytics:** A dedicated summary script to visualize your learning journey.
-   **Dialect Specific:** Explicitly configured for the Kolkata dialect (e.g., preferring "Jol" over "Pani").

## Project Structure

-   `practice.py`: The main interaction script for practice sessions.
-   `summary.py`: Generates statistics and identifies areas for improvement.
-   `progress.json`: The database tracking your vocabulary and grammar mastery.
-   `GEMINI.md`: Instructions and rules for the AI tutor.
-   `venv/`: Python virtual environment.

## Setup & Installation

### 1. System Dependencies (Linux/Ubuntu)
```bash
sudo apt update && sudo apt install -y python3-venv python3-pip mpg123
```

### 2. Python Environment
The project uses a virtual environment to manage dependencies:
```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### 3. API Key Configuration
This project requires a Google Gemini API key. You can obtain one for free (within certain limits) from the [Google AI Studio](https://aistudio.google.com/).

To use the key, set it as an environment variable in your terminal:
```bash
export GOOGLE_API_KEY="your_api_key_here"
```
Alternatively, the `practice.py` script will prompt you for the key if it's not found in your environment.

## How to Use

### Start a Practice Session
Run the main script and follow the prompts. The AI will automatically read your `progress.json` to tailor the session.
```bash
./venv/bin/python3 practice.py
```

### View Progress Summary
Check your mastery scores and see which words need more work:
```bash
./venv/bin/python3 summary.py
```

### Reset Progress
If you want to start over and reset all your mastery scores:
```bash
./venv/bin/python3 reset_progress.py
```
