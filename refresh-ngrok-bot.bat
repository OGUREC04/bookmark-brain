@echo off
setlocal EnableDelayedExpansion
title BB - Refresh ngrok URL + restart bot

REM Use case: ngrok died/rotated mid-session. Re-sync .env + bot menu button
REM without a full start.bat. Reuses the same URL extraction + update_env.py.

set PROJECT_DIR=%~dp0
set VENV_PY=%LOCALAPPDATA%\bookmark-brain\venv\Scripts\python.exe
set RUN_DIR=%PROJECT_DIR%tools\run

echo Getting current ngrok URL...
call :get_url

if "!NGROK_URL!"=="" (
    echo ngrok not responding. Restarting ngrok...
    start "BB ngrok" "%RUN_DIR%\ngrok.bat"
    echo Waiting 6 sec for ngrok...
    timeout /t 6 /nobreak >nul
    call :get_url
)

if "!NGROK_URL!"=="" (
    echo ERROR: still no ngrok URL on :4040 or :4041. Check BB ngrok window.
    goto :end
)

echo   ngrok URL: !NGROK_URL!
"%VENV_PY%" "%PROJECT_DIR%tools\update_env.py" MINI_APP_URL "!NGROK_URL!"
echo   .env updated

echo Killing existing bot process...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*bot.main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo   bot killed, waiting 12s to avoid TelegramConflictError...
timeout /t 12 /nobreak >nul

start "BB Bot" "%RUN_DIR%\bot.bat"
echo   bot restarted with fresh URL
echo.
echo ==========================================
echo   Done. Hard-close Mini App in Telegram and reopen.
echo   MINI_APP_URL: !NGROK_URL!
echo ==========================================
goto :end

:get_url
set NGROK_URL=
for /f "delims=" %%u in ('curl -s http://127.0.0.1:4040/api/tunnels ^| "%VENV_PY%" -c "import sys,json; d=json.load(sys.stdin); print(next((t['public_url'] for t in d.get('tunnels',[]) if t['public_url'].startswith('https')), ''))" 2^>nul') do set NGROK_URL=%%u
if "!NGROK_URL!"=="" (
    for /f "delims=" %%u in ('curl -s http://127.0.0.1:4041/api/tunnels ^| "%VENV_PY%" -c "import sys,json; d=json.load(sys.stdin); print(next((t['public_url'] for t in d.get('tunnels',[]) if t['public_url'].startswith('https')), ''))" 2^>nul') do set NGROK_URL=%%u
)
exit /b

:end
pause
endlocal
