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
-   `progress.json`: The database tracking your vocabulary and grammar mastery.
-   `GEMINI.md`: Instructions and rules for the AI tutor.
-   `venv/`: Python virtual environment (Linux).

## Setup & Installation

### Windows (Recommended for GUI)
Running natively on Windows provides the best support for **Bangla Script rendering** and **Windows Input Methods (IME)**.

> [!TIP]
> **Working with WSL Paths:** Windows tools often struggle with UNC paths (e.g., `\\wsl.localhost\...`). 
> For the best experience, map your WSL root to a drive letter:
> 1. Open PowerShell as Admin: `net use U: \\wsl.localhost\Ubuntu /persistent:yes`
> 2. Navigate via the drive letter: `cd U:\home\<user>\projects\bangla_bot`
> 3. Now run the setup and launch scripts from the `U:` drive.

1.  **Open PowerShell** and navigate to your project folder.
2.  **Run the Setup Script**:
    ```powershell
    Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process; .\setup_windows.ps1
    ```
3.  **Launch the App**:
    ```powershell
    .\launch_windows.ps1
    ```

### Linux / WSL
1.  **System Dependencies**:
    ```bash
    sudo apt update && sudo apt install -y python3-venv python3-pip mpg123
    ```
2.  **Python Environment**:
    ```bash
    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt
    ```

## API Key Configuration
This project requires a Google Gemini API key from [Google AI Studio](https://aistudio.google.com/).

-   **Windows (Permanent)**: 
    ```powershell
    [System.Environment]::SetEnvironmentVariable('GOOGLE_API_KEY', 'your-key-here', 'User')
    ```
-   **Linux/WSL**:
    ```bash
    export GOOGLE_API_KEY="your_api_key_here"
    ```

## How to Use

### Start the GUI (Windows)
```powershell
.\launch_windows.ps1
```

### Start the GUI (Linux/WSL)
```bash
./launch.sh
```

### Start the CLI Practice
```bash
./venv/bin/python3 practice.py
```

### View Progress Summary
```bash
./venv/bin/python3 summary.py
```

### Reset Progress
```bash
./venv/bin/python3 reset_progress.py
```
