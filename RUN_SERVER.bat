@echo off
setlocal EnableDelayedExpansion
title Albayan CCTV Monitor - Real Web Server
cd /d "%~dp0"

echo ======================================================================
echo   ALBAYAN LAB CCTV MONITOR - 4 CAMERAS REAL WEB SERVER
echo ======================================================================
echo.
echo   * Starting FastAPI Server on port 8899...
echo   * Connecting Cloudflare HTTPS Real Web Tunnel...
echo   * Master Passcode: 974621467097458841599745404128
echo   * 24-Hour Continuous Recording: Active
echo   * Telegram Alerts: Active
echo.
echo ======================================================================
echo.

set "PY_EXE="
python -c "import sys" >nul 2>nul
if !errorlevel! equ 0 set "PY_EXE=python"

if not defined PY_EXE (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "C:\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
    ) do (
        if not defined PY_EXE if exist "%%~P" set "PY_EXE=%%~P"
    )
)

if not defined PY_EXE set "PY_EXE=python"

"!PY_EXE!" server\server.py
pause
