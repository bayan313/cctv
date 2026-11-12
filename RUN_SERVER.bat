@echo off
setlocal
title Albayan CCTV Monitor - Real Web Server
cd /d "%~dp0"

echo ======================================================================
echo   ALBAYAN LAB CCTV MONITOR - 4 CAMERAS REAL WEB SERVER
echo ======================================================================
echo.
echo   * Starting FastAPI Server on port 8899...
echo   * Connecting Cloudflare HTTPS Real Web Tunnel...
echo   * Master Passcode: albayan@2026
echo   * Telegram Alerts: Active
echo.
echo ======================================================================
echo.

python server\server.py
pause
