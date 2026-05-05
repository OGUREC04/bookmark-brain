@echo off
title BB Worker
cd /d "%~dp0..\..\backend"
"%LOCALAPPDATA%\bookmark-brain\venv\Scripts\python.exe" run_worker.py
echo.
echo [BB Worker exited. Press any key to close.]
pause >nul
