@echo off
setlocal EnableDelayedExpansion
title Setup Study Monitor on this Computer
echo ========================================================
echo   LAB STUDY MONITOR - CLIENT INSTALLER (4 PCs)
echo ========================================================
echo.
echo Please enter the details for THIS computer:
echo.

set /p PC_NAME="Enter Computer Name (e.g. PC-1, PC-2, PC-3, PC-4) [Default: PC-1]: "
if "%PC_NAME%"=="" set PC_NAME=PC-1

set /p SERVER_IP="Enter Central Server IP (e.g. 192.168.1.3 or 127.0.0.1) [Default: 127.0.0.1]: "
if "%SERVER_IP%"=="" set SERVER_IP=127.0.0.1

echo.
echo Configuring for %PC_NAME% connecting to http://%SERVER_IP%:8899 ...

set SCRIPT_DIR=%~dp0
set CONFIG_FILE=%SCRIPT_DIR%client\client_config.json

(
echo {
echo   "computer_name": "%PC_NAME%",
echo   "server_url": "http://%SERVER_IP%:8899",
echo   "api_secret": "secure_study_monitor_secret_key_8899",
echo   "fps": 10,
echo   "chunk_minutes": 5
echo }
) > "%CONFIG_FILE%"

echo [OK] Saved configuration to client_config.json

:: Add to Windows Startup
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set VBS_LAUNCHER=%STARTUP_DIR%\StudyMonitorLauncher.vbs

echo Set WshShell = CreateObject("WScript.Shell") > "%VBS_LAUNCHER%"
echo WshShell.Run "pythonw """ ^& "%SCRIPT_DIR%client\recorder.py""" , 0, False >> "%VBS_LAUNCHER%"

echo.
echo ========================================================
echo   [SUCCESS] Installed on %PC_NAME%!
echo ========================================================
echo When this computer turns on:
echo   1. Waits 10 seconds.
echo   2. Displays popup alert for [%PC_NAME%].
echo   3. Records screen at 10 FPS and uploads to server.
echo ========================================================
echo.
pause
