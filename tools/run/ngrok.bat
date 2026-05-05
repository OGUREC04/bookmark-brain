@echo off
title BB ngrok
REM Kill stale ngrok so port 4040 is free — иначе новая сессия сядет на 4041
REM и update_env.py не найдёт её.
taskkill /F /IM ngrok.exe >nul 2>&1
timeout /t 2 /nobreak >nul
call npx ngrok http 3000
echo.
echo [BB ngrok exited. Press any key to close.]
pause >nul
