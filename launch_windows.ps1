$scriptPath = $MyInvocation.MyCommand.Path
$dir = Split-Path $scriptPath
Set-Location $dir

Write-Host "Working Directory: $dir" -ForegroundColor Gray

# Ensure ~/.local/bin is on PATH so uv is found even if not globally refreshed
$uvLocalBin = "$HOME\.local\bin"
if ((Test-Path $uvLocalBin) -and ($env:PATH -notlike "*$uvLocalBin*")) {
    $env:PATH = "$uvLocalBin;$env:PATH"
}

if (-not $env:GOOGLE_API_KEY) {
    Write-Host "GOOGLE_API_KEY not found in environment." -ForegroundColor Yellow
    $env:GOOGLE_API_KEY = Read-Host "Please paste your Google API Key"
} else {
    Write-Host "Using existing GOOGLE_API_KEY from environment." -ForegroundColor Green
}

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "Starting Bangla Bot GUI with uv..." -ForegroundColor Cyan
    uv run python gui_practice.py
} elseif (Test-Path ".\.venv\Scripts\python.exe") {
    Write-Host "Starting Bangla Bot GUI from .venv..." -ForegroundColor Cyan
    & ".\.venv\Scripts\python.exe" gui_practice.py
} else {
    Write-Error "Neither 'uv' nor '.venv' was found. Please run .\setup_windows.ps1 first."
}
pause
