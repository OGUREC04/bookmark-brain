@echo off
chcp 65001 >nul
title BookmarkBrain — Остановка

echo.
echo Останавливаю все сервисы BookmarkBrain...
echo.

:: Убиваем окна по заголовкам
taskkill /FI "WINDOWTITLE eq BB Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq BB Worker*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq BB Bot*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq BB Frontend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq BB ngrok*" /F >nul 2>&1

echo ✅ Все сервисы остановлены
echo.
echo Docker контейнеры оставлены работать.
echo Чтобы остановить Docker:
echo   docker compose down
echo.
pause
