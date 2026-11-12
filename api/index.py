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
from fastapi import FastAPI, Request, Response, HTTPException, Depends, UploadFile, File, Form, Header, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.security import APIKeyCookie

app = FastAPI(title="Albayan CCTV Lab Monitor - Real Web Cloud Portal")

cookie_scheme = APIKeyCookie(name="session_token", auto_error=False)
active_sessions = set()

# Configuration
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "albayan@2026")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9287027030:AAFeB2BZyF9G87R6ulycSzFFY9yIuqepIFQ")
API_SECRET = os.getenv("API_SECRET", "secure_study_monitor_secret_key_8899")
DEFAULT_PC_NAMES = ["albayan 1", "albayan 2", "albayan 3", "albayan 4"]

# Storage in /tmp for serverless runtime
TMP_DIR = Path("/tmp") if os.name != "nt" else (ROOT_DIR / "server" / "recordings")
TMP_RECORDINGS = TMP_DIR / "recordings"
try:
    TMP_RECORDINGS.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

client_pings = {}

def normalize_pc_name(name: str) -> str:
    clean = name.strip()
    c_up = clean.upper()
    if c_up in ["PC-01", "PC-1", "PC1"]:
        return "albayan 1"
    if c_up in ["PC-02", "PC-2", "PC2"]:
        return "albayan 2"
    if c_up in ["PC-03", "PC-3", "PC3"]:
        return "albayan 3"
    if c_up in ["PC-04", "PC-4", "PC4"]:
        return "albayan 4"
    return clean

def get_upstream_url(request: Optional[Request] = None) -> Optional[str]:
    # 1. Check environment variables
    env_url = os.getenv("LIVE_SERVER_URL") or os.getenv("PUBLIC_SERVER_URL")
    if env_url:
        return env_url.rstrip("/")
    # 2. Check cookie if passed
    if request:
        cookie_bridge = request.cookies.get("cctv_bridge_url")
        if cookie_bridge and cookie_bridge.startswith("http"):
            return cookie_bridge.rstrip("/")
    # 3. Check config.json if present
    try:
        cfg_file = ROOT_DIR / "config.json"
        if cfg_file.exists():
            with open(cfg_file, "r", encoding="utf-8") as f:
                c = json.load(f)
                pub = c.get("public_web_url")
                if pub and pub.startswith("http"):
                    return pub.rstrip("/")
    except Exception:
        pass
    return None

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

# ----------------- HTML TEMPLATES -----------------

def get_html_dashboard():
    try:
        from server.server import get_cctv_dashboard_html as get_full_html
        return get_full_html()
    except Exception as e:
        # Fallback full dashboard
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Albayan CCTV Monitor - Real Web Portal</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col items-center justify-center p-4">
  <div class="max-w-md w-full bg-slate-900 border border-slate-800 rounded-3xl p-6 text-center space-y-4">
    <div class="w-12 h-12 bg-emerald-600 rounded-2xl mx-auto flex items-center justify-center text-white text-xl">
      <i class="fa-solid fa-video"></i>
    </div>
    <h1 class="text-xl font-bold text-white">Albayan CCTV Real Web Portal</h1>
    <p class="text-slate-400 text-xs">CCTV Core loading or bridge connecting...</p>
    <a href="/login" class="block w-full bg-emerald-600 hover:bg-emerald-500 py-2.5 rounded-xl text-white font-bold text-sm">Enter Dashboard</a>
  </div>
</body>
</html>"""

def get_html_login():
    try:
        from server.server import get_login_html as get_full_login
        return get_full_login()
    except Exception:
        return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Albayan CCTV Lab - Real Web Login</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
</head>
<body class="bg-slate-950 flex items-center justify-center min-h-screen p-4 text-slate-100 font-sans">
  <div class="w-full max-w-md bg-slate-900 border border-slate-800 rounded-3xl p-8 shadow-2xl space-y-6">
    <div class="text-center space-y-2">
      <div class="inline-flex items-center justify-center w-12 h-12 bg-emerald-600/20 text-emerald-400 rounded-2xl border border-emerald-500/30">
        <i class="fa-solid fa-shield-halved text-xl"></i>
      </div>
      <h1 class="text-2xl font-bold tracking-tight text-white">Albayan CCTV Lab</h1>
      <p class="text-xs text-slate-400">Real Web Surveillance Portal</p>
    </div>
    <form id="loginForm" class="space-y-4">
      <div>
        <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Master Passcode</label>
        <input type="password" id="password" placeholder="Enter albayan@2026" required
          class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-emerald-500 transition">
      </div>
      <div id="loginError" class="text-xs text-red-400 hidden text-center font-medium">Invalid passcode. Please try again.</div>
      <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-3 px-4 rounded-xl transition text-sm shadow-lg shadow-emerald-600/20">
        Unlock CCTV Dashboard
      </button>
    </form>
  </div>
  <script>
    document.getElementById('loginForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const pw = document.getElementById('password').value;
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ password: pw })
      });
      if (res.ok) {
        window.location.href = '/';
      } else {
        document.getElementById('loginError').classList.remove('hidden');
      }
    });
  </script>
</body>
</html>"""

# ----------------- MAIN WEB ROUTES -----------------

@app.get("/", response_class=HTMLResponse)
@app.get("/api", response_class=HTMLResponse)
@app.get("/api/", response_class=HTMLResponse)
@app.get("/api/index.py", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/cctv", response_class=HTMLResponse)
def index_page(request: Request, session_token: Optional[str] = Depends(cookie_scheme)):
    if not session_token or session_token not in active_sessions:
        return get_html_login()
    return get_html_dashboard()

@app.get("/login", response_class=HTMLResponse)
def login_page(session_token: Optional[str] = Depends(cookie_scheme)):
    if session_token and session_token in active_sessions:
        return get_html_dashboard()
    return get_html_login()

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
        active_sessions.discard(session_token)
    response.delete_cookie("session_token")
    return {"ok": True}

# ----------------- CCTV IMAGE & STREAM API -----------------

@app.get("/api/live/{computer_name}")
def get_live_frame(computer_name: str, request: Request):
    clean = normalize_pc_name(computer_name)
    upstream = get_upstream_url(request)

    # 1. Try upstream proxy if available
    if upstream:
        try:
            r = requests.get(f"{upstream}/api/live/{clean}", timeout=3.5)
            if r.status_code == 200 and r.content:
                return Response(content=r.content, media_type=r.headers.get("content-type", "image/jpeg"))
        except Exception:
            pass

    # 2. Try locally saved live frame in /tmp or recordings
    local_live = TMP_DIR / f"live_{clean}.jpg"
    if local_live.exists():
        try:
            return Response(content=local_live.read_bytes(), media_type="image/jpeg")
        except Exception:
            pass

    # 3. Clean, high-tech CCTV camera standby overlay
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
      <defs>
        <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
          <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1e293b" stroke-width="1"/>
        </pattern>
      </defs>
      <rect width="960" height="540" fill="#020617"/>
      <rect width="960" height="540" fill="url(#grid)" opacity="0.6"/>
      <rect x="20" y="20" width="920" height="500" fill="none" stroke="#059669" stroke-width="1.5" stroke-dasharray="10 6" opacity="0.4"/>
      <!-- Crosshairs -->
      <path d="M 460 270 L 500 270 M 480 250 L 480 290" stroke="#10b981" stroke-width="2" opacity="0.7"/>
      <!-- CCTV Header OSD -->
      <text x="40" y="55" fill="#34d399" font-family="monospace" font-size="16" font-weight="bold">CAM // {clean.upper()}</text>
      <text x="40" y="80" fill="#64748b" font-family="monospace" font-size="12">STATUS: STANDBY / AWAITING SIGNAL</text>
      <text x="920" y="55" fill="#94a3b8" font-family="monospace" font-size="14" text-anchor="end">{now_str}</text>
      <!-- Center Text -->
      <circle cx="480" cy="270" r="60" fill="none" stroke="#059669" stroke-width="1.5" opacity="0.5"/>
      <text x="480" y="360" fill="#cbd5e1" font-family="monospace" font-size="15" font-weight="bold" text-anchor="middle">LIVE SIGNAL STANDBY</text>
      <text x="480" y="385" fill="#64748b" font-family="monospace" font-size="12" text-anchor="middle">Ready for real-time transmission</text>
    </svg>"""
    return Response(content=svg, media_type="image/svg+xml")

@app.get("/api/screenshots")
def get_screenshots(computer: str = "albayan 1", request: Request = None, session: str = Depends(verify_session)):
    clean = normalize_pc_name(computer)
    upstream = get_upstream_url(request)

    if upstream:
        try:
            r = requests.get(f"{upstream}/api/screenshots?computer={clean}", headers={"Cookie": f"session_token={session}"}, timeout=3.5)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass

    return {
        "computer": clean,
        "total": 0,
        "screenshots": []
    }

@app.get("/api/status")
def get_system_status(request: Request, session: str = Depends(verify_session)):
    upstream = get_upstream_url(request)

    if upstream:
        try:
            r = requests.get(f"{upstream}/api/status", headers={"Cookie": f"session_token={session}"}, timeout=3.5)
            if r.status_code == 200:
                data = r.json()
                data["public_web_url"] = upstream
                return data
        except Exception:
            pass

    now = time.time()
    computers_list = []
    online_count = 0

    for name in DEFAULT_PC_NAMES:
        last_ping = client_pings.get(name, 0)
        is_online = (now - last_ping) < 90
        if is_online:
            online_count += 1
        computers_list.append({
            "name": name,
            "is_online": is_online,
            "ip": "Real Web Node",
            "snapshots_count": 0,
            "last_seen_seconds": int(now - last_ping) if last_ping else None
        })

    return {
        "server_ip": "real-web-portal",
        "server_port": 443,
        "public_web_url": request.base_url._url.rstrip("/"),
        "computers": computers_list,
        "total_online": online_count,
        "total_snapshots": 0,
        "total_size_mb": 0,
        "telegram_connected": bool(TELEGRAM_BOT_TOKEN),
        "retention_hours": 24
    }

# ----------------- CLIENT DIRECT UPLOAD API -----------------

@app.post("/api/client/live_frame")
async def client_live_frame(
    request: Request,
    computer_name: str = Form(...),
    frame: UploadFile = File(...),
    x_api_secret: Optional[str] = Header(None)
):
    if x_api_secret != API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid API Secret")

    clean = normalize_pc_name(computer_name)
    client_pings[clean] = time.time()

    content = await frame.read()
    dest = TMP_DIR / f"live_{clean}.jpg"
    try:
        dest.write_bytes(content)
    except Exception:
        pass

    return {"status": "ok"}

@app.post("/api/client/ping")
def client_ping(payload: dict, x_api_secret: Optional[str] = Header(None)):
    if x_api_secret != API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid API Secret")
    name = normalize_pc_name(payload.get("computer_name", "albayan 1"))
    client_pings[name] = time.time()
    return {"status": "pong"}

@app.post("/api/client/register")
def client_register(payload: dict):
    return {
        "computer_name": "albayan 1",
        "server_url": "real-web",
        "api_secret": API_SECRET
    }

# ----------------- DOWNLOAD SETUP SCRIPT -----------------

@app.get("/api/download/setup-script")
def download_setup_script(request: Request, session: str = Depends(verify_session)):
    base_url = str(request.base_url).rstrip("/")
    script_content = f"""@echo off
setlocal
title Albayan CCTV Study Monitor - Real Web Client Setup
echo ========================================================
echo   ALBAYAN LAB MONITOR - 1-CLICK REAL WEB CLIENT SETUP
echo ========================================================
echo.

set TARGET_DIR=%LOCALAPPDATA%\\AlbayanMonitor
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
if not exist "%TARGET_DIR%\\client" mkdir "%TARGET_DIR%\\client"
if not exist "%TARGET_DIR%\\client\\temp_records" mkdir "%TARGET_DIR%\\client\\temp_records"

echo [1/3] Downloading latest software from Real Web Portal...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('{base_url}/api/download/recorder.py', '%TARGET_DIR%\\client\\recorder.py')"

echo.
echo [2/3] Installing lightweight dependencies...
python -m pip install mss requests truststore pillow numpy --quiet

echo.
echo [3/3] Setting up Windows Auto-Startup (HKCU Run)...
reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "AlbayanStudyMonitorClient" /t REG_SZ /d "pythonw \"%TARGET_DIR%\\client\\recorder.py\"" /f >nul

echo.
echo Starting Screen Monitor in Background...
start "" pythonw "%TARGET_DIR%\\client\\recorder.py"

echo.
echo ========================================================
echo   [SUCCESS] SETUP COMPLETE! PC IS TRANSMITTING TO CCTV!
echo ========================================================
pause
"""
    return Response(
        content=script_content,
        media_type="application/bat",
        headers={"Content-Disposition": "attachment; filename=albayan_setup.bat"}
    )

@app.get("/api/download/recorder.py")
def download_recorder_py():
    rec_file = ROOT_DIR / "client" / "recorder.py"
    if rec_file.exists():
        return FileResponse(rec_file, media_type="text/x-python", filename="recorder.py")
    try:
        r = requests.get("https://raw.githubusercontent.com/bayan313/cctv/main/client/recorder.py", timeout=5)
        if r.status_code == 200:
            return Response(content=r.content, media_type="text/x-python")
    except Exception:
        pass
    raise HTTPException(status_code=404, detail="recorder.py not found")

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    path = request.url.path
    if path.startswith("/api/") and not any(path.startswith(p) for p in ["/api/login", "/api/logout", "/api/download"]):
        return JSONResponse(status_code=404, content={"detail": f"Route {path} not found"})
    token = request.cookies.get("session_token")
    if token and token in active_sessions:
        return HTMLResponse(get_html_dashboard())
    return HTMLResponse(get_html_login())
