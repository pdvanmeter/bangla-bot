@echo off
pushd "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

if "%GOOGLE_API_KEY%"=="" (
    echo Error: GOOGLE_API_KEY environment variable is not set.
    set /p API_KEY="Please enter your Google API Key: "
    set GOOGLE_API_KEY=%API_KEY%
)

where uv >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo Starting with uv...
    uv run python gui_practice.py
) else (
    echo Starting with .venv...
    .\.venv\Scripts\python.exe gui_practice.py
)
popd
pause
