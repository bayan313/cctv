# -*- coding: utf-8 -*-
import os
import json
import time
import secrets
import sys
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import requests
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import APIKeyCookie

app = FastAPI(title="Albayan CCTV Lab Monitor - Cloud Portal")

cookie_scheme = APIKeyCookie(name="session_token", auto_error=False)
active_sessions = set()

# Configuration
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "albayan@2026")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9287027030:AAFeB2BZyF9G87R6ulycSzFFY9yIuqepIFQ")
API_SECRET = os.getenv("API_SECRET", "secure_study_monitor_secret_key_8899")
LOCAL_SERVER_URL = os.getenv("LOCAL_SERVER_URL", "http://192.168.1.2:8899")
DEFAULT_PC_NAMES = ["albayan 1", "albayan 2", "albayan 3", "albayan 4"]

def verify_session(session_token: Optional[str] = Depends(cookie_scheme)):
    if not session_token or session_token not in active_sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return session_token

@app.middleware("http")
async def vercel_path_normalizer(request: Request, call_next):
    path = request.scope.get("path", "")
    for prefix in ["/api/index.py", "/api/index"]:
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    if not path:
        path = "/"
    request.scope["path"] = path
    return await call_next(request)

# ----------------- ROUTES -----------------

@app.get("/", response_class=HTMLResponse)
@app.get("/api", response_class=HTMLResponse)
@app.get("/api/", response_class=HTMLResponse)
@app.get("/api/index.py", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/cctv", response_class=HTMLResponse)
def index_page(request: Request, session_token: Optional[str] = Depends(cookie_scheme)):
    if not session_token or session_token not in active_sessions:
        return get_login_html()
    return get_cctv_dashboard_html()

@app.post("/api/login")
@app.post("/login")
def login(payload: dict, response: Response):
    password = payload.get("password")
    if password == ADMIN_PASSWORD:
        token = secrets.token_hex(24)
        active_sessions.add(token)
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            max_age=86400 * 7,
            samesite="lax"
        )
        return {"ok": True, "token": token}
    raise HTTPException(status_code=401, detail="Invalid password")

@app.post("/api/logout")
@app.post("/logout")
def logout(response: Response, session_token: Optional[str] = Depends(cookie_scheme)):
    if session_token in active_sessions:
        active_sessions.remove(session_token)
    response.delete_cookie("session_token")
    return {"ok": True}

@app.get("/api/download/setup-script")
def download_setup_script(session: str = Depends(verify_session)):
    """Downloads installer from GitHub repository directly."""
    script_content = """@echo off
setlocal
title Albayan CCTV Study Monitor - Auto Installer
echo ========================================================
echo   ALBAYAN LAB MONITOR - 1-CLICK CLIENT INSTALLER
echo ========================================================
echo.

set TARGET_DIR=%LOCALAPPDATA%\\AlbayanMonitor
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
if not exist "%TARGET_DIR%\\client" mkdir "%TARGET_DIR%\\client"
if not exist "%TARGET_DIR%\\client\\temp_records" mkdir "%TARGET_DIR%\\client\\temp_records"

echo [1/3] Downloading latest software from GitHub...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://raw.githubusercontent.com/bayan313/cctv/main/client/recorder.py', '%TARGET_DIR%\\client\\recorder.py')"

echo.
echo [2/3] Installing dependencies...
python -m pip install mss requests truststore pillow numpy --quiet

echo.
echo [3/3] Setting up Windows Auto-Startup (HKCU Run)...
reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "AlbayanStudyMonitorClient" /t REG_SZ /d "pythonw \"%TARGET_DIR%\\client\\recorder.py\"" /f >nul

echo.
echo Starting Screen Monitor in Background...
start "" pythonw "%TARGET_DIR%\\client\\recorder.py"

echo.
echo ========================================================
echo   [SUCCESS] INSTALLED SUCCESSFULLY!
echo ========================================================
pause
"""
    return Response(
        content=script_content,
        media_type="application/bat",
        headers={"Content-Disposition": "attachment; filename=albayan_cctv_setup.bat"}
    )

@app.get("/api/status")
def get_system_status(session: str = Depends(verify_session)):
    computers = []
    for name in DEFAULT_PC_NAMES:
        computers.append({
            "name": name,
            "is_online": False,
            "ip": "Standby / Cloud Node",
            "snapshots_count": 0
        })

    return {
        "server_ip": "vercel-cloud.app",
        "server_port": 443,
        "computers": computers,
        "total_online": 0,
        "total_snapshots": 0,
        "total_size_mb": 0,
        "telegram_connected": bool(TELEGRAM_BOT_TOKEN),
        "retention_hours": 24
    }

@app.get("/api/screenshots")
def get_screenshots(computer: str = "albayan 1", session: str = Depends(verify_session)):
    return {
        "computer": computer,
        "total": 0,
        "screenshots": []
    }

@app.get("/api/live/{computer_name}")
def get_live_frame(computer_name: str):
    # In cloud serverless, return SVG placeholder
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
      <rect width="960" height="540" fill="#0f172a"/>
      <rect x="80" y="80" width="800" height="380" fill="none" stroke="#334155" stroke-width="2"/>
      <text x="100" y="120" fill="#64748b" font-family="monospace" font-size="18">CAM // {computer_name.upper()}</text>
      <text x="480" y="270" fill="#ef4444" font-family="monospace" font-size="24" text-anchor="middle">[ CLOUD PROXY MODE ]</text>
      <text x="480" y="310" fill="#94a3b8" font-family="monospace" font-size="14" text-anchor="middle">Local CCTV Server running on {LOCAL_SERVER_URL}</text>
    </svg>"""
    return Response(content=svg, media_type="image/svg+xml")

def get_login_html():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Albayan CCTV Monitor - Login</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 flex items-center justify-center min-h-screen p-4 text-slate-100">
  <div class="w-full max-w-md bg-slate-900 border border-slate-800 rounded-3xl p-8 shadow-2xl">
    <div class="text-center mb-6">
      <h1 class="text-2xl font-bold tracking-tight text-white">Albayan CCTV Lab</h1>
      <p class="text-xs text-slate-400 mt-1">4-Screen Surveillance Dashboard</p>
    </div>
    <form id="loginForm" class="space-y-4">
      <input type="password" id="password" placeholder="Master Password" required class="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white">
      <div id="loginError" class="hidden text-xs text-rose-400 bg-rose-500/10 p-3 rounded-xl"></div>
      <button type="submit" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-3 rounded-xl transition text-sm">Sign In</button>
    </form>
  </div>
  <script>
    document.getElementById('loginForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const pwd = document.getElementById('password').value;
      const res = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: pwd }) });
      if (res.ok) window.location.reload();
      else {
        document.getElementById('loginError').innerText = 'Wrong passcode?';
        document.getElementById('loginError').classList.remove('hidden');
      }
    });
  </script>
</body>
</html>"""

def get_cctv_dashboard_html():
    hub_url = LOCAL_SERVER_URL.strip() if LOCAL_SERVER_URL else "http://192.168.1.2:8899"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Albayan CCTV Monitor - Cloud Portal</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen p-4 md:p-8 flex flex-col items-center justify-center">
  <div class="max-w-2xl w-full bg-slate-900 border border-slate-800 rounded-3xl p-6 md:p-10 shadow-2xl space-y-6">
    
    <div class="text-center space-y-2">
      <div class="inline-flex items-center gap-2 px-3 py-1 bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 rounded-full text-xs font-semibold tracking-wider uppercase">
        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
        Albayan CCTV Cloud Node Active
      </div>
      <h1 class="text-2xl md:text-3xl font-extrabold tracking-tight text-white">Albayan CCTV Lab Hub</h1>
      <p class="text-slate-400 text-sm">4-Computer Real-Time Screen Monitoring & Review</p>
    </div>

    <!-- Info Box: LAN vs Mobile -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="bg-slate-950/60 border border-slate-800 rounded-2xl p-5 space-y-3">
        <div class="flex items-center gap-2 text-indigo-400 font-bold text-sm">
          <i class="fa-solid fa-wifi text-lg"></i>
          <span>Lab Wi-Fi / LAN Access</span>
        </div>
        <p class="text-xs text-slate-400 leading-relaxed">
          When connected to the <strong>Lab Wi-Fi</strong>, open the central local hub for full 720p 4-camera live stream and 5-min timeline:
        </p>
        <a href="{hub_url}" target="_blank" rel="noopener noreferrer" class="flex items-center justify-center gap-2 w-full bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-3 px-4 rounded-xl transition text-sm shadow-lg shadow-indigo-600/20">
          <i class="fa-solid fa-tv"></i>
          <span>Open Live CCTV ({hub_url})</span>
        </a>
      </div>

      <div class="bg-slate-950/60 border border-slate-800 rounded-2xl p-5 space-y-3">
        <div class="flex items-center gap-2 text-sky-400 font-bold text-sm">
          <i class="fa-brands fa-telegram text-lg"></i>
          <span>Anywhere via Mobile Data</span>
        </div>
        <p class="text-xs text-slate-400 leading-relaxed">
          Outside the lab on 4G/5G? Get instant live screen snapshots and alerts directly on your phone via Telegram:
        </p>
        <a href="https://t.me/my_library_data_bot" target="_blank" rel="noopener noreferrer" class="flex items-center justify-center gap-2 w-full bg-sky-600 hover:bg-sky-500 text-white font-bold py-3 px-4 rounded-xl transition text-sm shadow-lg shadow-sky-600/20">
          <i class="fa-solid fa-paper-plane"></i>
          <span>Open @my_library_data_bot</span>
        </a>
      </div>
    </div>

    <!-- System Status Badges -->
    <div class="bg-slate-950 border border-slate-800 rounded-2xl p-4 flex flex-wrap items-center justify-between text-xs gap-3">
      <div class="flex items-center gap-2">
        <span class="text-slate-400">Hub Server:</span>
        <code class="bg-slate-800 px-2 py-1 rounded text-indigo-300 font-mono">{hub_url}</code>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-slate-400">Passcode:</span>
        <code class="bg-slate-800 px-2 py-1 rounded text-emerald-300 font-mono">albayan@2026</code>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-slate-400">Monitored PCs:</span>
        <span class="text-white font-medium">albayan 1, 2, 3, 4</span>
      </div>
    </div>

    <!-- Installer Download -->
    <div class="pt-2">
      <a href="/api/download/setup-script" download="albayan_setup.bat" class="flex items-center justify-center gap-2 w-full bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 font-semibold py-3 px-4 rounded-xl transition text-sm">
        <i class="fa-solid fa-download"></i>
        <span>Download 1-Click Client Setup (.bat) for Lab PCs</span>
      </a>
    </div>

  </div>
</body>
</html>"""

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    path = request.url.path
    # Return JSON error only for real API calls that failed
    if path.startswith("/api/") and not any(path.startswith(p) for p in ["/api/login", "/api/logout", "/api/download"]):
        return JSONResponse(status_code=404, content={"detail": f"Route {path} not found"})
    token = request.cookies.get("session_token")
    if token and token in active_sessions:
        return HTMLResponse(get_cctv_dashboard_html())
    return HTMLResponse(get_login_html())
