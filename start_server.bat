@echo off
title Study Monitor Web Portal
cd /d "%~dp0"
echo ========================================================
echo   STUDY MONITOR - WEB DASHBOARD & SERVER
echo ========================================================
echo Starting server on http://localhost:8899 ...
echo Press Ctrl+C to stop.
echo.
python server\server.py
pause
