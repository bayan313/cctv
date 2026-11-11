@echo off
setlocal
title Albayan Study Monitor - One Click Setup
cd /d "%~dp0"

echo ========================================================
echo   ALBAYAN LAB MONITOR - 1-CLICK AUTOMATIC INSTALLER
echo ========================================================
echo.
echo [1/3] Detecting Server and Auto-Assigning Computer Name...
python -c "from client.recorder import auto_register_pc; cfg = auto_register_pc(); print('>> Assigned Name: ' + cfg['computer_name'])"

echo.
echo [2/3] Adding to Windows Automatic Startup...
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set VBS_LAUNCHER=%STARTUP_DIR%\StudyMonitorLauncher.vbs

echo Set WshShell = CreateObject("WScript.Shell") > "%VBS_LAUNCHER%"
echo WshShell.Run "pythonw """ ^& "%~dp0client\recorder.py""" , 0, False >> "%VBS_LAUNCHER%"

echo.
echo [3/3] Starting Monitor in Background...
start "" pythonw client\recorder.py

echo.
echo ========================================================
echo   [SUCCESS] SETUP COMPLETE!
echo ========================================================
echo This PC will now:
echo   - Start automatically whenever the computer turns ON
echo   - Wait 10 seconds and display the popup warning
echo   - Record at 10 FPS and upload to your Web Dashboard
echo   - Auto-update safely whenever you push to GitHub!
echo ========================================================
echo.
pause
