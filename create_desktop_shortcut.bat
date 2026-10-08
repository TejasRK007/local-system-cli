@echo off
cd /d "%~dp0"
echo ========================================================
echo   Creating Desktop Shortcut for AI Manager Dashboard...
echo ========================================================
echo.
cscript //nologo "%~dp0create_shortcut.vbs"
echo.
echo [SUCCESS] Double-click "AI Manager Dashboard" on your Desktop anytime to launch!
echo.
pause
