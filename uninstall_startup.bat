@echo off
setlocal
echo ========================================================
echo   STUDY MONITOR - REMOVE FROM WINDOWS STARTUP
echo ========================================================
echo.

set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set VBS_LAUNCHER=%STARTUP_DIR%\StudyMonitorLauncher.vbs

if exist "%VBS_LAUNCHER%" (
    del "%VBS_LAUNCHER%"
    echo [SUCCESS] Removed Study Monitor from Windows Startup.
) else (
    echo [INFO] Startup launcher was not installed or already removed.
)

echo.
pause
