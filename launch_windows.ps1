$scriptPath = $MyInvocation.MyCommand.Path
$dir = Split-Path $scriptPath
Set-Location $dir

Write-Host "Working Directory: $dir" -ForegroundColor Gray

# UNC Path Compatibility Hack (for WSL)
if ($dir.StartsWith("\\")) {
    Write-Host "UNC path detected. Mapping temporary drive for compatibility..." -ForegroundColor Yellow
    $driveLetter = "Z"
    for ($i = 90; $i -ge 65; $i--) {
        $letter = [char]$i + ":"
        if (-not (Test-Path $letter)) {
            $driveLetter = [char]$i
            break
        }
    }
    New-PSDrive -Name $driveLetter -PSProvider FileSystem -Root $dir -Scope Global | Out-Null
    Set-Location ("$driveLetter" + ":\")
    Write-Host "Mapped to $driveLetter:\" -ForegroundColor Gray
}

if (-not $env:GOOGLE_API_KEY) {
    Write-Host "Warning: GOOGLE_API_KEY not found in environment." -ForegroundColor Yellow
    $env:GOOGLE_API_KEY = Read-Host "Please enter your Google API Key"
}

if (Get-Command conda -ErrorAction SilentlyContinue) {
    Write-Host "Attempting to start with Conda..." -ForegroundColor Cyan
    $json = conda info --json | ConvertFrom-Json
    $envRoot = $json.envs | Where-Object { $_.EndsWith("bangla_bot") -or $_.EndsWith("\bangla_bot") }
    
    if ($envRoot) {
        $pythonPath = Join-Path $envRoot "python.exe"
        Write-Host "Found Python at: $pythonPath" -ForegroundColor Gray
        & "$pythonPath" gui_practice.py
    } else {
        Write-Host "Conda environment 'bangla_bot' not found. Falling back to 'conda run'..." -ForegroundColor Yellow
        conda run -n bangla_bot python gui_practice.py
    }
} else {
    Write-Host "Starting with Venv..." -ForegroundColor Cyan
    $pythonPath = ".\venv\Scripts\python.exe"
    if (Test-Path $pythonPath) {
        & "$pythonPath" gui_practice.py
    } else {
        Write-Error "Virtual environment not found at .\venv"
    }
}
pause
