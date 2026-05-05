@echo off
setlocal EnableDelayedExpansion
title BookmarkBrain - Startup

set PROJECT_DIR=%~dp0
set BACKEND_DIR=%PROJECT_DIR%backend
set FRONTEND_DIR=%PROJECT_DIR%frontend
set RUN_DIR=%PROJECT_DIR%tools\run
set VENV_DIR=%LOCALAPPDATA%\bookmark-brain\venv
set VENV_PY=%VENV_DIR%\Scripts\python.exe
set LOG=%PROJECT_DIR%startup.log

echo. > "%LOG%"
echo ================================ >> "%LOG%"
echo BookmarkBrain startup %date% %time% >> "%LOG%"
echo ================================ >> "%LOG%"
echo VENV_PY=%VENV_PY% >> "%LOG%"
echo. >> "%LOG%"

echo ==========================================
echo   BookmarkBrain - startup
echo ==========================================
echo Log: %LOG%
echo.

echo [0/7] Pre-flight...
if not exist "%VENV_PY%" (
    echo ERROR: venv not found at %VENV_DIR%
    echo        Run install.bat first.
    goto :fail
)
if not exist "%BACKEND_DIR%\main.py" (
    echo ERROR: backend\main.py not found
    goto :fail
)
if not exist "%PROJECT_DIR%.env" (
    echo ERROR: .env not found
    goto :fail
)
"%VENV_PY%" -c "import alembic, uvicorn, arq, aiogram" 1>>"%LOG%" 2>&1
if !errorlevel! neq 0 (
    echo ERROR: venv missing deps. Re-run install.bat
    goto :fail
)
echo   OK
echo.

echo [1/7] Docker compose up...
pushd "%PROJECT_DIR%"
docker compose up -d 1>>"%LOG%" 2>&1
set ERR=!errorlevel!
popd
if !ERR! neq 0 (
    echo ERROR: docker compose failed. See %LOG%
    goto :fail
)
echo   OK
echo.

echo Waiting 4 sec for postgres/redis...
timeout /t 4 /nobreak >nul

echo [2/7] Alembic migrations...
pushd "%BACKEND_DIR%"
"%VENV_PY%" -m alembic upgrade head 1>>"%LOG%" 2>&1
set ERR=!errorlevel!
popd
if !ERR! neq 0 (
    echo ERROR: alembic failed. See %LOG%
    goto :fail
)
echo   OK
echo.

echo [3/7] Backend (port 8000)...
start "BB Backend" "%RUN_DIR%\backend.bat"
timeout /t 5 /nobreak >nul
curl -s -m 3 http://localhost:8000/health >nul 2>&1
if !errorlevel! neq 0 (
    echo   WARN: /health did not respond yet. Check BB Backend window.
) else (
    echo   OK
)
echo.

echo [4/7] AI Worker...
start "BB Worker" "%RUN_DIR%\worker.bat"
timeout /t 2 /nobreak >nul
echo   started
echo.

echo [5/7] Telegram Bot... (deferred until ngrok URL is known)
echo.

echo [6/7] Frontend (port 3000)...
start "BB Frontend" "%RUN_DIR%\frontend.bat"
timeout /t 3 /nobreak >nul
echo   started
echo.

echo [7/7] ngrok tunnel...
start "BB ngrok" "%RUN_DIR%\ngrok.bat"
echo Waiting 5 sec for ngrok...
timeout /t 5 /nobreak >nul

for /f "delims=" %%u in ('curl -s http://127.0.0.1:4040/api/tunnels ^| "%VENV_PY%" -c "import sys,json; d=json.load(sys.stdin); print(next((t['public_url'] for t in d.get('tunnels',[]) if t['public_url'].startswith('https')), ''))" 2^>nul') do set NGROK_URL=%%u

REM Fallback: ngrok может сесть на 4041 если 4040 занят зомби-процессом
if "%NGROK_URL%"=="" (
    for /f "delims=" %%u in ('curl -s http://127.0.0.1:4041/api/tunnels ^| "%VENV_PY%" -c "import sys,json; d=json.load(sys.stdin); print(next((t['public_url'] for t in d.get('tunnels',[]) if t['public_url'].startswith('https')), ''))" 2^>nul') do set NGROK_URL=%%u
)

if "%NGROK_URL%"=="" (
    echo WARN: could not get ngrok URL. Check BB ngrok window and http://127.0.0.1:4040 / :4041
    echo Starting bot anyway with stale URL...
) else (
    echo   ngrok URL: %NGROK_URL%
    "%VENV_PY%" "%PROJECT_DIR%tools\update_env.py" MINI_APP_URL "%NGROK_URL%"
    echo   .env updated
)

echo Starting Telegram Bot with fresh URL...
start "BB Bot" "%RUN_DIR%\bot.bat"
timeout /t 2 /nobreak >nul
echo.

echo ==========================================
echo   All services started
echo ==========================================
echo Backend:  http://localhost:8000/health
echo Frontend: http://localhost:3000
echo ngrok:    http://127.0.0.1:4040
echo.
echo If any BB-window shows a traceback - that is the problem.
echo Windows stay open on failure.
echo.
goto :end

:fail
echo.
echo ==========================================
echo   STARTUP FAILED
echo ==========================================
echo See %LOG% for details.
echo.

:end
pause
endlocal
