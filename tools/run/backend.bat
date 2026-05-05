@echo off
title BB Backend
cd /d "%~dp0..\..\backend"
"%LOCALAPPDATA%\bookmark-brain\venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000
echo.
echo [BB Backend exited. Press any key to close.]
pause >nul
