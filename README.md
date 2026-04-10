# Bangla Bot: Kolkata Dialect Tutor 🇮🇳

An interactive, programmatic Bengali language learning environment focused on the Kolkata dialect. This project uses Gemini to generate contextual practice sessions, track progress, and provide real-time audio feedback.

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
source venv/bin/activate
pip install -r requirements.txt
```

## How to Use

### Start a Practice Session
Run the main script and follow the prompts. Type "Start session" to begin.
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

## Version Control
This project is initialized with Git. To connect it to your GitHub account:
```bash
git remote add origin <your-repo-url>
git add .
git commit -m "Initial commit"
git push -u origin main
```
