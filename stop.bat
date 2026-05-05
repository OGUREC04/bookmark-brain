@echo off
chcp 65001 >nul
title BookmarkBrain — Остановка

echo.
echo Останавливаю все сервисы BookmarkBrain...
echo.

:: Убиваем окна по заголовкам
taskkill /FI "WINDOWTITLE eq BookmarkBrain Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq BookmarkBrain Worker*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq BookmarkBrain Bot*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq BookmarkBrain Frontend*" /F >nul 2>&1

echo ✅ Все сервисы остановлены
echo.
echo Docker контейнеры оставлены работать.
echo Чтобы остановить Docker:
echo   docker compose down
echo.
pause
