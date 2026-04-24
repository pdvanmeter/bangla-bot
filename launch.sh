#!/bin/bash

# Force software rendering to avoid WSL2 GPU driver issues (Mesa/Zink)
export LIBGL_ALWAYS_SOFTWARE=1

# Navigate to the script directory (optional, but good for portability)
cd "$(dirname "$0")"

# Run the application using the local virtual environment
echo "Starting Bangla Bot GUI with software rendering..."
./venv/bin/python gui_practice.py
