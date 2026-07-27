@echo off
setlocal EnableExtensions EnableDelayedExpansion
title AI WeChat Production System - Start
cd /d "%~dp0"

echo.
echo ========================================
echo   AI WeChat Production System - Start
echo ========================================
echo.

where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker was not found. Install Docker Desktop first.
  echo.
  pause
  exit /b 1
)

docker info >nul 2>&1
if not errorlevel 1 goto DOCKER_READY

echo [INFO] Docker Desktop is not running. Trying to start it...
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" goto START_DOCKER
echo [ERROR] Docker Desktop was not found. Start it manually and retry.
echo.
pause
exit /b 1

:START_DOCKER
start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set /a WAIT_COUNT=0

:WAIT_DOCKER
timeout /t 3 /nobreak >nul
docker info >nul 2>&1
if not errorlevel 1 goto DOCKER_READY
set /a WAIT_COUNT+=1
if !WAIT_COUNT! GEQ 40 goto DOCKER_TIMEOUT
echo [WAIT] Docker is starting... !WAIT_COUNT!/40
goto WAIT_DOCKER

:DOCKER_TIMEOUT
echo [ERROR] Docker Desktop startup timed out.
echo.
pause
exit /b 1

:DOCKER_READY
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo [INFO] The .env file has been created.
  echo [ACTION] Fill in the API key and passwords, then run this file again.
  echo.
  pause
  exit /b 1
)

echo [START] Starting PostgreSQL, backend, frontend, n8n and Adminer...
docker compose up -d
if errorlevel 1 (
  echo.
  echo [ERROR] Startup failed. Review the error message above.
  pause
  exit /b 1
)

echo.
echo ========================================
echo   Startup completed successfully
echo ========================================
echo Review UI: http://localhost:8080
echo n8n:       http://localhost:5678
echo Adminer:   http://localhost:8081
echo API docs:  http://localhost:8000/docs
echo.
if /i "%NO_BROWSER%"=="1" goto NO_BROWSER
start "" "http://localhost:8080"
:NO_BROWSER
if /i "%NO_PAUSE%"=="1" exit /b 0
pause
