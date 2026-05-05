@echo off
title BB Bot
cd /d "%~dp0..\.."
"%LOCALAPPDATA%\bookmark-brain\venv\Scripts\python.exe" -m bot.main
echo.
echo [BB Bot exited. Press any key to close.]
pause >nul
