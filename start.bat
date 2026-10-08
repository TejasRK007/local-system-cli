@echo off
title AI Manager — Local Agentic Automation
cd /d "%~dp0"

echo ===================================================
echo   Starting AI Manager Local Dashboard...
echo ===================================================
echo.

:: Activate virtualenv if present
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

:: Launch web dashboard (automatically opens browser at http://127.0.0.1:8000)
python -m app.main ui

if errorlevel 1 (
    echo.
    echo [ERROR] Dashboard stopped unexpectedly.
    pause
)
