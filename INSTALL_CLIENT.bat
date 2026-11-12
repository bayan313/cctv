@echo off
setlocal EnableDelayedExpansion
title Albayan CCTV Study Monitor - Client Setup
cd /d "%~dp0"

echo ========================================================
echo   ALBAYAN LAB CCTV MONITOR - AUTOMATIC CLIENT SETUP
echo ========================================================
echo.

:: 1. Check if Standalone AlbayanMonitor.exe is available in dist folder
if exist "%~dp0dist\AlbayanMonitor.exe" (
    echo [1/3] Found Standalone AlbayanMonitor.exe (Zero Python needed)...
    echo [2/3] Adding to Windows Automatic Startup (HKCU Run)...
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "AlbayanStudyMonitorClient" /t REG_SZ /d "\"%~dp0dist\AlbayanMonitor.exe\"" /f >nul

    set "VBS_FILE=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\StudyMonitorClient.vbs"
    (
        echo Set WshShell = CreateObject^("WScript.Shell"^)
        echo WshShell.Run Chr^(34^) ^& "%~dp0dist\AlbayanMonitor.exe" ^& Chr^(34^), 0, False
    ) > "!VBS_FILE!" 2>nul

    echo [3/3] Starting CCTV Screen Monitor in Background...
    start "" "%~dp0dist\AlbayanMonitor.exe"
    goto success
)

:: 2. Fallback: Locate working Python environment
echo [1/3] Detecting Python environment...
set "PY_EXE="
set "PYW_EXE="

python -c "import sys" >nul 2>nul
if !errorlevel! equ 0 (
    for /f "delims=" %%I in ('where python') do if not defined PY_EXE set "PY_EXE=%%I"
    for /f "delims=" %%I in ('where pythonw') do if not defined PYW_EXE set "PYW_EXE=%%I"
)

if not defined PY_EXE (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
        "C:\Python310\python.exe"
    ) do (
        if not defined PY_EXE if exist "%%~P" (
            "%%~P" -c "import sys" >nul 2>nul
            if !errorlevel! equ 0 (
                set "PY_EXE=%%~P"
                set "PYW_EXE=%%~dpPpythonw.exe"
            )
        )
    )
)

if not defined PY_EXE (
    echo.
    echo ========================================================
    echo   [!] Python is NOT installed on this PC.
    echo   [!] Downloading official Python automatically...
    echo ========================================================
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe', '%TEMP%\py_setup.exe')"
    start /wait "" "%TEMP%\py_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 SimpleInstall=1
    del "%TEMP%\py_setup.exe" >nul 2>nul

    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    ) do (
        if not defined PY_EXE if exist "%%~P" (
            set "PY_EXE=%%~P"
            set "PYW_EXE=%%~dpPpythonw.exe"
        )
    )
)

if not defined PY_EXE (
    echo [ERROR] Could not find or install Python. Please install Python from python.org.
    pause
    exit /b 1
)

if not defined PYW_EXE set "PYW_EXE=!PY_EXE!"
echo [OK] Python detected: !PY_EXE!

echo.
echo [2/3] Installing lightweight dependencies...
"!PY_EXE!" -m pip install mss requests truststore pillow numpy imageio imageio-ffmpeg --quiet --no-warn-script-location

echo.
echo [3/3] Setting up Windows Auto-Startup on PC Boot...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "AlbayanStudyMonitorClient" /t REG_SZ /d "\"!PYW_EXE!\" \"%~dp0client\recorder.py\"" /f >nul

set "VBS_FILE=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\StudyMonitorClient.vbs"
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WshShell.Run Chr^(34^) ^& "!PYW_EXE!" ^& Chr^(34^) ^& " " ^& Chr^(34^) ^& "%~dp0client\recorder.py" ^& Chr^(34^), 0, False
) > "!VBS_FILE!" 2>nul

start "" "!PYW_EXE!" "%~dp0client\recorder.py"

:success
echo.
echo ========================================================
echo   [SUCCESS] SETUP COMPLETE!
echo ========================================================
echo This PC will now:
echo   - Start automatically whenever the computer turns ON
echo   - Wait 10 seconds and display the popup warning
echo   - Capture screenshots every 5 minutes (CCTV Timeline)
echo   - Transmit live screen feed to Web CCTV Dashboard
echo   - Auto-update safely whenever updates are pushed to GitHub!
echo ========================================================
echo.
pause
