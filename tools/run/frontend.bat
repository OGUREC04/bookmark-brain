@echo off
title BB Frontend
cd /d "%~dp0..\..\frontend"
call npx vite --host
echo.
echo [BB Frontend exited. Press any key to close.]
pause >nul
