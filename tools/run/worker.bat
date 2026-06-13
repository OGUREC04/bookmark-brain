@echo off
title BB Worker
cd /d "%~dp0..\..\backend"
REM Repo root on PYTHONPATH so the worker can import the shared/ package (3sr)
set "PYTHONPATH=%~dp0..\.."
"%LOCALAPPDATA%\bookmark-brain\venv\Scripts\python.exe" run_worker.py
echo.
echo [BB Worker exited. Press any key to close.]
pause >nul
