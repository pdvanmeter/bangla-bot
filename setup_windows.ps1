# setup_windows.ps1

$projectName = "bangla_bot"
$envName = "bangla_bot"

Write-Host "--- 🇧🇩 Bangla Bot Windows Setup ---" -ForegroundColor Cyan

# 1. Environment Detection & Creation
if (Get-Command conda -ErrorAction SilentlyContinue) {
    Write-Host "[Detected Conda]" -ForegroundColor Green
    $condaEnvs = conda env list | Out-String
    if ($condaEnvs -match $envName) {
        Write-Host "Conda environment '$envName' already exists."
    } else {
        Write-Host "Creating Conda environment '$envName'..."
        conda create -n $envName python=3.12 -y
    }
    Write-Host "To activate, use: conda activate $envName" -ForegroundColor Yellow
} else {
    Write-Host "[Conda not found, falling back to Venv]" -ForegroundColor Gray
    if (-not (Test-Path "venv")) {
        Write-Host "Creating virtual environment..."
        python -m venv venv
    }
    Write-Host "Activating Venv..."
    # Note: Execution policy might need to be set for scripts
    Write-Host "You may need to run: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process" -ForegroundColor Cyan
}

# 2. Dependency Installation
Write-Host "Installing/Updating dependencies..." -ForegroundColor Cyan
if (Get-Command conda -ErrorAction SilentlyContinue) {
    conda run -n $envName pip install -r requirements.txt
} else {
    .\venv\Scripts\pip.exe install -r requirements.txt
}

# 3. Create a Windows Launcher (Batch file)
# pushd handles UNC paths by mapping a temporary drive letter
$launchContent = @"
@echo off
pushd "%~dp0"
if "%GOOGLE_API_KEY%"=="" (
    echo Error: GOOGLE_API_KEY environment variable is not set.
    set /p API_KEY="Please enter your Google API Key: "
    set GOOGLE_API_KEY=%API_KEY%
)
where conda >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo Starting with Conda...
    conda run -n $envName python gui_practice.py
) else (
    echo Starting with Venv...
    .\venv\Scripts\python.exe gui_practice.py
)
popd
pause
"@
$launchContent | Out-File -FilePath "launch_windows.bat" -Encoding ascii

# 4. Create a PowerShell Launcher (Best for UNC/WSL paths)
$psLaunchContent = @"
`$scriptPath = `$MyInvocation.MyCommand.Path
`$dir = Split-Path `$scriptPath
Set-Location `$dir

Write-Host "Working Directory: `$dir" -ForegroundColor Gray

# UNC Path Compatibility Hack (for WSL)
if (`$dir.StartsWith("\\")) {
    Write-Host "UNC path detected. Mapping temporary drive for compatibility..." -ForegroundColor Yellow
    `$driveLetter = "Z"
    for (`$i = 90; `$i -ge 65; `$i--) {
        `$letter = [char]`$i + ":"
        if (-not (Test-Path `$letter)) {
            `$driveLetter = [char]`$i
            break
        }
    }
    New-PSDrive -Name `$driveLetter -PSProvider FileSystem -Root `$dir -Scope Global | Out-Null
    Set-Location ("`$driveLetter" + ":\")
    Write-Host "Mapped to `$driveLetter`:\" -ForegroundColor Gray
}

if (-not `$env:GOOGLE_API_KEY) {
    Write-Host "GOOGLE_API_KEY not found in environment." -ForegroundColor Yellow
    `$env:GOOGLE_API_KEY = Read-Host "Please paste your Google API Key"
} else {
    Write-Host "Using existing GOOGLE_API_KEY from environment." -ForegroundColor Green
}

if (Get-Command conda -ErrorAction SilentlyContinue) {
    Write-Host "Attempting to start with Conda..." -ForegroundColor Cyan
    `$json = conda info --json | ConvertFrom-Json
    `$envRoot = `$json.envs | Where-Object { `$_.EndsWith("$envName") -or `$_.EndsWith("\$envName") }

    if (`$envRoot) {
        `$pythonPath = Join-Path `$envRoot "python.exe"
        Write-Host "Found Python at: `$pythonPath" -ForegroundColor Gray
        # Use direct execution to keep the environment variables in the same process
        & "`$pythonPath" gui_practice.py
    } else {
        Write-Host "Conda environment '$envName' not found. Falling back to 'conda run'..." -ForegroundColor Yellow
        conda run --no-capture-output -n $envName python gui_practice.py
    }
}
 else {
    Write-Host "Starting with Venv..." -ForegroundColor Cyan
    `$pythonPath = ".\venv\Scripts\python.exe"
    if (Test-Path `$pythonPath) {
        & "`$pythonPath" gui_practice.py
    } else {
        Write-Error "Virtual environment not found at .\venv"
    }
}
pause
"@
$psLaunchContent | Out-File -FilePath "launch_windows.ps1" -Encoding ascii

Write-Host "`n--- Setup Complete ---" -ForegroundColor Green
Write-Host "1. Created 'launch_windows.bat' (Batch) and 'launch_windows.ps1' (PowerShell)."
Write-Host "2. Running from WSL paths is now supported via 'pushd'."
Write-Host "3. For best results, run: .\launch_windows.ps1"
