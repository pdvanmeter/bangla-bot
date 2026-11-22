#!/bin/bash

# Force software rendering to avoid WSL2 GPU driver issues (Mesa/Zink)
export LIBGL_ALWAYS_SOFTWARE=1
export PATH="$HOME/.local/bin:$PATH"

# Navigate to the script directory
cd "$(dirname "$0")"

# Run the application using uv
echo "Starting Bangla Bot GUI with software rendering..."
uv run python gui_practice.py
