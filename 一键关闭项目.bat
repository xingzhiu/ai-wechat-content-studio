@echo off
setlocal EnableExtensions
title AI WeChat Production System - Stop
cd /d "%~dp0"

echo.
echo ========================================
echo   AI WeChat Production System - Stop
echo ========================================
echo.

where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker was not found.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo [INFO] Docker Desktop is not running. The project is already unavailable.
  pause
  exit /b 0
)

docker compose stop
if errorlevel 1 (
  echo.
  echo [ERROR] Stop failed. Review the error message above.
  pause
  exit /b 1
)

echo.
echo [DONE] The project has stopped.
echo [SAFE] Database, images, exports and history were preserved.
echo.
if /i "%NO_PAUSE%"=="1" exit /b 0
pause
