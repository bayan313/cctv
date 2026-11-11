@echo off
cd /d "%~dp0"
:: Start recorder silently in background using pythonw (no terminal window)
start "" pythonw client\recorder.py
