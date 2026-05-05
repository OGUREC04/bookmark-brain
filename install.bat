@echo off
setlocal EnableDelayedExpansion
title BookmarkBrain - Install

set PROJECT_DIR=%~dp0
set BACKEND_DIR=%PROJECT_DIR%backend
set BOT_DIR=%PROJECT_DIR%bot
set PYTHON=C:\Users\nicha\AppData\Local\Programs\Python\Python313\python.exe
set VENV_DIR=%LOCALAPPDATA%\bookmark-brain\venv
set VENV_PY=%VENV_DIR%\Scripts\python.exe
set LOG=%PROJECT_DIR%install.log

echo. > "%LOG%"
echo ================================ >> "%LOG%"
echo BookmarkBrain install %date% %time% >> "%LOG%"
echo ================================ >> "%LOG%"
echo VENV_DIR=%VENV_DIR% >> "%LOG%"
echo. >> "%LOG%"

echo ==========================================
echo   BookmarkBrain - one-time setup
echo ==========================================
echo venv will be at: %VENV_DIR%
echo log: %LOG%
echo.

if not exist "%PYTHON%" (
    echo ERROR: Python not found at %PYTHON%
    goto :fail
)

if exist "%VENV_PY%" (
    echo [1/3] venv already exists, skipping create
) else (
    echo [1/3] Creating venv...
    "%PYTHON%" -m venv "%VENV_DIR%" 1>>"%LOG%" 2>&1
    if !errorlevel! neq 0 (
        echo ERROR: venv creation failed. See %LOG%
        goto :fail
    )
    echo   OK
)
echo.

echo [2/3] Upgrading pip...
"%VENV_PY%" -m pip install --upgrade pip 1>>"%LOG%" 2>&1
echo   OK
echo.

echo [3/3] Installing requirements (1-3 min)...
echo   backend/requirements.txt
"%VENV_PY%" -m pip install --prefer-binary --timeout 120 --retries 5 --index-url https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r "%BACKEND_DIR%\requirements.txt" 1>>"%LOG%" 2>&1
if !errorlevel! neq 0 (
    echo ERROR: backend requirements failed. See %LOG%
    echo HINT: If pydantic-core wheel build failed, Python 3.14 may lack pre-built wheels.
    goto :fail
)
echo   backend OK

if exist "%BOT_DIR%\requirements.txt" (
    echo   bot/requirements.txt
    "%VENV_PY%" -m pip install --prefer-binary --timeout 120 --retries 5 --index-url https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r "%BOT_DIR%\requirements.txt" 1>>"%LOG%" 2>&1
    if !errorlevel! neq 0 (
        echo ERROR: bot requirements failed. See %LOG%
        goto :fail
    )
    echo   bot OK
)

echo.
echo ==========================================
echo   Setup complete
echo ==========================================
echo venv: %VENV_DIR%
echo.
echo Now run start.bat
echo.
goto :end

:fail
echo.
echo ==========================================
echo   INSTALL FAILED
echo ==========================================
echo See %LOG% for details.

:end
pause
endlocal
