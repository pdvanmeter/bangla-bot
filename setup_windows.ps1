# setup_windows.ps1

Write-Host "--- 🇧🇩 Bangla Bot Windows Setup (uv) ---" -ForegroundColor Cyan

# Ensure ~/.local/bin is in PATH for this session
$uvLocalBin = "$HOME\.local\bin"
if ((Test-Path $uvLocalBin) -and ($env:PATH -notlike "*$uvLocalBin*")) {
    $env:PATH = "$uvLocalBin;$env:PATH"
}

# 1. Check / Install uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[uv not found] Installing uv..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:PATH = "$HOME\.local\bin;$env:PATH"
} else {
    $uvVer = uv --version
    Write-Host "[Detected $uvVer]" -ForegroundColor Green
}

# 2. Sync Environment & Dependencies
Write-Host "Syncing virtual environment and dependencies with uv..." -ForegroundColor Cyan
uv sync

Write-Host "`n--- Setup Complete ---" -ForegroundColor Green
Write-Host "To start the GUI: .\launch_windows.ps1  (or: uv run python gui_practice.py)"
Write-Host "To start the CLI: uv run python practice.py"
