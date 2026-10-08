@echo off
title AI Manager — Local Agentic Automation (HTTPS)
cd /d "%~dp0"

echo ===================================================
echo   Starting AI Manager Dashboard in HTTPS Mode...
echo   (Enables live phone camera QR scanning on LAN)
echo ===================================================
echo.

:: Activate virtualenv if present
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

:: Launch web dashboard in HTTPS mode (automatically opens browser at https://127.0.0.1:8443)
python -m app.main https-ui

if errorlevel 1 (
    echo.
    echo [ERROR] HTTPS Dashboard stopped unexpectedly.
    pause
)
