# -*- coding: utf-8 -*-
import os
import sys
import shutil
import pathlib
import winreg

BASE_DIR = pathlib.Path(__file__).resolve().parent
SERVER_PY = BASE_DIR / "server" / "server.py"
CLIENT_PY = BASE_DIR / "client" / "recorder.py"
CLIENT_EXE = BASE_DIR / "dist" / "AlbayanMonitor.exe"
if not CLIENT_EXE.exists():
    CLIENT_EXE = BASE_DIR.parent / "dist" / "AlbayanMonitor.exe"

# Always resolve pythonw from sys.executable's real directory to avoid dummy WindowsApps alias stubs
py_dir = pathlib.Path(sys.executable).parent
cand = py_dir / "pythonw.exe"
if cand.exists():
    pythonw_exe = str(cand)
else:
    pythonw_exe = sys.executable

print(f"[Setup Startup] Base Directory: {BASE_DIR}")
print(f"[Setup Startup] Pythonw:        {pythonw_exe}")
print(f"[Setup Startup] Server Path:    {SERVER_PY} (Exists: {SERVER_PY.exists()})")
print(f"[Setup Startup] Client Path:    {CLIENT_PY} (Exists: {CLIENT_PY.exists()})")
print(f"[Setup Startup] Client EXE:     {CLIENT_EXE} (Exists: {CLIENT_EXE.exists()})")

# 1. Update Windows Registry (HKCU Run)
import time
server_cmd = f'"{pythonw_exe}" "{SERVER_PY}"'
client_cmd = f'"{CLIENT_EXE}"' if CLIENT_EXE.exists() else f'"{pythonw_exe}" "{CLIENT_PY}"'

for attempt in range(5):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "AlbayanStudyMonitorServer", 0, winreg.REG_SZ, server_cmd)
        winreg.SetValueEx(key, "AlbayanStudyMonitorClient", 0, winreg.REG_SZ, client_cmd)
        winreg.CloseKey(key)
        print("✅ [Registry] Successfully updated HKCU Run with real executable:")
        print(f"   AlbayanStudyMonitorServer -> {server_cmd}")
        print(f"   AlbayanStudyMonitorClient -> {client_cmd}")
        break
    except Exception as e:
        if attempt == 4:
            print(f"❌ [Registry Error] {e}")
        time.sleep(0.8)

# 2. Update Windows Startup Folder (Dual redundancy)
try:
    appdata = os.environ.get("APPDATA")
    if appdata:
        startup = pathlib.Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        startup.mkdir(parents=True, exist_ok=True)
        
        server_vbs = startup / "StudyMonitorServer.vbs"
        client_vbs = startup / "StudyMonitorClient.vbs"

        # Clean escape sequences for VBS
        s_script = f'Set WshShell = CreateObject("WScript.Shell")\r\nWshShell.CurrentDirectory = "{BASE_DIR}"\r\nWshShell.Run """{pythonw_exe}"" ""{SERVER_PY}""", 0, False\r\n'
        if CLIENT_EXE.exists():
            c_script = f'Set WshShell = CreateObject("WScript.Shell")\r\nWshShell.Run """{CLIENT_EXE}""", 0, False\r\n'
        else:
            c_script = f'Set WshShell = CreateObject("WScript.Shell")\r\nWshShell.CurrentDirectory = "{BASE_DIR}"\r\nWshShell.Run """{pythonw_exe}"" ""{CLIENT_PY}""", 0, False\r\n'

        server_vbs.write_text(s_script, encoding="utf-8")
        client_vbs.write_text(c_script, encoding="utf-8")

        print("✅ [Startup Folder] Successfully updated VBS scripts:")
        print("   -", server_vbs)
        print("   -", client_vbs)
except Exception as e:
    print(f"ℹ️ [Startup Folder Notice] Registry HKCU Run active: {e}")

print("\n🎉 [SUCCESS] Computer will now start the monitoring tool automatically when turned ON!")
