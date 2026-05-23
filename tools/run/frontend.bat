@echo off
title BB Frontend
REM Frontend extracted to sibling repo bookmark-brain-miniapp (see .claude/STARTUP.md).
cd /d "%~dp0..\..\..\bookmark-brain-miniapp"
call npx vite --host
echo.
echo [BB Frontend exited. Press any key to close.]
pause >nul
