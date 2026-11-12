# -*- coding: utf-8 -*-
import os
import io
import json
import time
import secrets
import hmac
import hashlib
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
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "974621467097458841599745404128")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9287027030:AAFeB2BZyF9G87R6ulycSzFFY9yIuqepIFQ")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "8003387798"))
API_SECRET = os.getenv("API_SECRET", "secure_study_monitor_secret_key_8899")
DEFAULT_PC_NAMES = ["albayan 1", "albayan 2", "albayan 3", "albayan 4"]

def send_telegram_message(text: str):
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception:
        pass

def send_telegram_video(video_bytes: bytes, filename: str, caption: str):
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    try:
        requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
            files={"video": (filename, io.BytesIO(video_bytes), "video/mp4")},
            timeout=30
        )
    except Exception as e:
        print(f"[Telegram Vercel] Error sending video: {e}")

def create_session_token() -> str:
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    msg = f"{ts}:{nonce}:{ADMIN_PASSWORD}"
    sig = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{ts}.{nonce}.{sig}"

def is_valid_session_token(token: Optional[str]) -> bool:
    if not token or not isinstance(token, str):
        return False
    if token in active_sessions:
        return True
    parts = token.split(".")
    if len(parts) != 3:
        return False
    ts, nonce, sig = parts
    try:
        created = int(ts)
        # 30-day persistent session
        if time.time() - created > 86400 * 30 or created > time.time() + 300:
            return False
    except ValueError:
        return False
    for pw in ["974621467097458841599745404128", ADMIN_PASSWORD, "albayan@2026"]:
        if not pw:
            continue
        msg = f"{ts}:{nonce}:{pw}"
        expected_sig = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, expected_sig):
            return True
    return False

def verify_session(session_token: Optional[str] = Depends(cookie_scheme)):
    if not session_token or not is_valid_session_token(session_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return session_token

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
    env_url = os.getenv("LIVE_SERVER_URL") or os.getenv("PUBLIC_SERVER_URL")
    if env_url:
        return env_url.rstrip("/")
    if request:
        cookie_bridge = request.cookies.get("cctv_bridge_url")
        if cookie_bridge and cookie_bridge.startswith("http"):
            return cookie_bridge.rstrip("/")
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
        return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Albayan CCTV Monitor - Real Web Portal</title>
  <script>
    (function() {
      try {
        var navEntries = (performance.getEntriesByType && performance.getEntriesByType("navigation")) || [];
        var isReload = (navEntries.length > 0 && navEntries[0].type === "reload") || (performance.navigation && performance.navigation.type === 1);
        if (isReload) {
          document.cookie = "session_token=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
          if (navigator.sendBeacon) { navigator.sendBeacon("/api/logout"); } else { fetch("/api/logout", { method: "POST" }); }
          window.location.replace("/login");
        }
      } catch(e) {}
    })();
  </script>
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
        <input type="password" id="password" placeholder="Enter 974621467097458841599745404128" required
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
    if not session_token or not is_valid_session_token(session_token):
        return get_html_login()
    return get_html_dashboard()

@app.get("/login", response_class=HTMLResponse)
def login_page(session_token: Optional[str] = Depends(cookie_scheme)):
    if session_token and is_valid_session_token(session_token):
        return get_html_dashboard()
    return get_html_login()

@app.post("/api/login")
@app.post("/login")
def login(payload: dict, request: Request, response: Response):
    password = str(payload.get("password", "")).strip()
    valid_passwords = {"974621467097458841599745404128", "albayan@2026"}
    if ADMIN_PASSWORD:
        valid_passwords.add(str(ADMIN_PASSWORD).strip())
    if password in valid_passwords:
        token = create_session_token()
        active_sessions.add(token)
        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie(
            key="session_token",
            value=token,
            path="/",
            httponly=True,
            max_age=86400 * 30,
            samesite="lax",
            secure=is_https
        )
        return {"ok": True, "token": token}
    raise HTTPException(status_code=401, detail="Invalid password")

@app.post("/api/logout")
@app.post("/logout")
def logout(response: Response, session_token: Optional[str] = Depends(cookie_scheme)):
    if session_token in active_sessions:
        active_sessions.discard(session_token)
    response.delete_cookie("session_token", path="/")
    return {"ok": True}

@app.get("/api/settings")
def get_settings(session: str = Depends(verify_session)):
    cfg_file = ROOT_DIR / "config.json"
    cfg = {}
    if cfg_file.exists():
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "retention_hours": cfg.get("retention_hours", 24),
        "video_fps": cfg.get("video_fps", 10),
        "video_chunk_minutes": cfg.get("video_chunk_minutes", 2),
        "send_videos_to_telegram": cfg.get("send_videos_to_telegram", True),
        "video_recording_enabled": cfg.get("video_recording_enabled", True),
        "live_stream_interval_seconds": cfg.get("live_stream_interval_seconds", 5),
        "screenshot_interval_seconds": cfg.get("screenshot_interval_seconds", 300),
        "admin_password": ADMIN_PASSWORD
    }

@app.post("/api/settings")
def update_settings(payload: dict, session: str = Depends(verify_session)):
    cfg_file = ROOT_DIR / "config.json"
    cfg = {}
    if cfg_file.exists():
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    if "retention_hours" in payload:
        cfg["retention_hours"] = max(1, int(payload["retention_hours"]))
    if "video_fps" in payload:
        cfg["video_fps"] = max(1, min(60, int(payload["video_fps"])))
    if "video_chunk_minutes" in payload:
        cfg["video_chunk_minutes"] = max(1, min(60, int(payload["video_chunk_minutes"])))
    if "send_videos_to_telegram" in payload:
        cfg["send_videos_to_telegram"] = bool(payload["send_videos_to_telegram"])
    if "video_recording_enabled" in payload:
        cfg["video_recording_enabled"] = bool(payload["video_recording_enabled"])
    if "live_stream_interval_seconds" in payload:
        cfg["live_stream_interval_seconds"] = max(1, min(60, int(payload["live_stream_interval_seconds"])))
    if "screenshot_interval_seconds" in payload:
        cfg["screenshot_interval_seconds"] = max(10, min(3600, int(payload["screenshot_interval_seconds"])))
    if "admin_password" in payload and payload["admin_password"]:
        cfg["admin_password"] = str(payload["admin_password"]).strip()
    try:
        cfg_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass
    return {"ok": True, "message": "Settings updated successfully"}

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

@app.get("/api/recordings")
def get_recordings(
    computer: Optional[str] = Query(None),
    request: Request = None,
    session: str = Depends(verify_session)
):
    upstream = get_upstream_url(request)
    target = f"?computer={computer}" if computer else ""
    if upstream:
        try:
            r = requests.get(f"{upstream}/api/recordings{target}", headers={"Cookie": f"session_token={session}"}, timeout=5)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass

    results = []
    all_videos = list(TMP_RECORDINGS.glob("*.mp4"))
    all_videos.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    target_pc = normalize_pc_name(computer) if computer and computer.lower() != "all" else None

    from datetime import datetime
    for f in all_videos:
        name = f.name
        pc_name = "unknown"
        time_label = ""
        date_label = ""
        full_str = ""
        try:
            if name.startswith("[") and "]_" in name:
                parts = name.split("]_")
                pc_name = parts[0][1:].strip()
                ts_part = parts[1].replace(".mp4", "")
                dt = datetime.strptime(ts_part, "%Y%m%d_%H%M%S")
                time_label = dt.strftime("%I:%M %p")
                date_label = dt.strftime("%b %d, %Y")
                full_str = dt.strftime("%Y-%m-%d %I:%M:%S %p")
        except Exception:
            pass

        if not full_str:
            mtime = f.stat().st_mtime
            full_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %I:%M:%S %p")
            time_label = datetime.fromtimestamp(mtime).strftime("%I:%M %p")
            date_label = datetime.fromtimestamp(mtime).strftime("%b %d, %Y")

        if target_pc and pc_name.lower() != target_pc.lower():
            continue

        results.append({
            "filename": f.name,
            "computer": pc_name,
            "url": f"/api/video/{f.name}",
            "time_label": time_label,
            "date_label": date_label,
            "created_at": full_str,
            "timestamp": f.stat().st_mtime,
            "size_mb": round(f.stat().st_size / (1024 * 1024), 2)
        })

    return {
        "total": len(results),
        "recordings": results
    }

@app.get("/api/video/{filename}")
def serve_video(filename: str, request: Request = None):
    upstream = get_upstream_url(request)
    if upstream:
        from fastapi.responses import RedirectResponse
        try:
            return RedirectResponse(url=f"{upstream}/api/video/{filename}")
        except Exception:
            pass

    safe_name = Path(filename).name
    path = TMP_RECORDINGS / safe_name
    if path.exists() and path.suffix.lower() == ".mp4":
        return FileResponse(
            path,
            media_type="video/mp4",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Disposition": f'inline; filename="{safe_name}"'
            }
        )
    raise HTTPException(status_code=404, detail="Video not found")

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

@app.get("/api/ping")
def ping_health():
    return {"ok": True, "status": "online"}

@app.post("/api/client/upload_video")
@app.post("/api/client/upload")
async def client_upload_video(
    request: Request,
    video: UploadFile = File(...),
    computer_name: str = Form("albayan 1"),
    x_api_secret: Optional[str] = Header(None)
):
    if x_api_secret != API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid API Secret")

    clean = normalize_pc_name(computer_name)
    client_pings[clean] = time.time()
    dest = TMP_RECORDINGS / video.filename
    content = b""
    try:
        content = await video.read()
        dest.write_bytes(content)
    except Exception:
        pass

    if content:
        import html
        from datetime import datetime
        file_size_mb = round(len(content) / (1024 * 1024), 2)
        now_str = datetime.now().strftime("%I:%M %p")
        caption = (
            f"📹 <b>[{html.escape(clean.upper())}] Screen Video Recording</b>\n"
            f"🕒 Time: {now_str}\n"
            f"📁 File: <code>{html.escape(video.filename)}</code>\n"
            f"📦 Size: {file_size_mb} MB"
        )
        try:
            send_telegram_video(content, video.filename, caption)
        except Exception:
            pass

    return {"ok": True, "filename": video.filename}

@app.post("/api/client/boot_notify")
def client_boot_notify(payload: dict, request: Request, x_api_secret: Optional[str] = Header(None)):
    if x_api_secret != API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid API Secret")
    name = normalize_pc_name(payload.get("computer_name", "albayan 1"))
    client_pings[name] = time.time()
    import html
    from datetime import datetime
    now_str = datetime.now().strftime("%I:%M:%S %p")
    client_ip = request.client.host if request.client else "unknown"
    send_telegram_message(
        f"🚨 <b>[{html.escape(name.upper())}] Computer Turned ON!</b>\n"
        f"🕒 Time: <b>{now_str}</b>\n"
        f"🌐 IP: <code>{client_ip}</code>\n"
        f"📹 Automatic screen video recording & CCTV live stream started."
    )
    return {"ok": True}

@app.post("/api/client/ping")
def client_ping(payload: dict, x_api_secret: Optional[str] = Header(None)):
    if x_api_secret != API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid API Secret")
    name = normalize_pc_name(payload.get("computer_name", "albayan 1"))
    client_pings[name] = time.time()
    cfg_file = ROOT_DIR / "config.json"
    cfg = {}
    if cfg_file.exists():
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "status": "pong",
        "config": {
            "video_fps": cfg.get("video_fps", 10),
            "video_chunk_minutes": cfg.get("video_chunk_minutes", 2),
            "video_recording_enabled": cfg.get("video_recording_enabled", True),
            "live_stream_interval_seconds": cfg.get("live_stream_interval_seconds", 5),
            "screenshot_interval_seconds": cfg.get("screenshot_interval_seconds", 300)
        }
    }

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
setlocal EnableDelayedExpansion
title Albayan CCTV Study Monitor - Universal Client Setup
echo ========================================================
echo   ALBAYAN LAB MONITOR - 1-CLICK UNIVERSAL CLIENT SETUP
echo ========================================================
echo.

set "TARGET_DIR=%LOCALAPPDATA%\\AlbayanMonitor"
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
if not exist "%TARGET_DIR%\\client" mkdir "%TARGET_DIR%\\client"
if not exist "%TARGET_DIR%\\client\\temp_records" mkdir "%TARGET_DIR%\\client\\temp_records"

echo [1/4] Checking Python environment...
set "PY_EXE="
set "PYW_EXE="

:: Step A: Test if python in PATH is real and working (ignores dummy Microsoft Store 0-byte aliases)
python -c "import sys" >nul 2>nul
if !errorlevel! equ 0 (
    where pythonw >nul 2>nul
    if !errorlevel! equ 0 (
        for /f "delims=" %%I in ('where python') do if not defined PY_EXE set "PY_EXE=%%I"
        for /f "delims=" %%I in ('where pythonw') do if not defined PYW_EXE set "PYW_EXE=%%I"
    )
)

:: Step B: If not in PATH or broken, check standard Python locations
if not defined PY_EXE (
    for %%P in (
        "%LOCALAPPDATA%\\Programs\\Python\\Python313\\python.exe"
        "%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe"
        "%LOCALAPPDATA%\\Programs\\Python\\Python311\\python.exe"
        "%LOCALAPPDATA%\\Programs\\Python\\Python310\\python.exe"
        "C:\\Python313\\python.exe"
        "C:\\Python312\\python.exe"
        "C:\\Python311\\python.exe"
        "C:\\Python310\\python.exe"
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

:: Step C: If Python is STILL missing, auto-install official Python silently (no admin needed)
if not defined PY_EXE (
    echo.
    echo ========================================================
    echo   [!] Python is NOT installed on this PC.
    echo   [!] Installing official Python automatically...
    echo   (Silent setup in user space - please wait ~20 sec)
    echo ========================================================
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe', '%TEMP%\\py_setup.exe')"
    start /wait "" "%TEMP%\\py_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 SimpleInstall=1
    del "%TEMP%\\py_setup.exe" >nul 2>nul
    
    for %%P in (
        "%LOCALAPPDATA%\\Programs\\Python\\Python311\\python.exe"
        "%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe"
        "%LOCALAPPDATA%\\Programs\\Python\\Python313\\python.exe"
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
echo [OK] Silent runner:  !PYW_EXE!

echo.
echo [2/4] Downloading latest CCTV monitoring client...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('{base_url}/api/download/recorder.py', '%TARGET_DIR%\\client\\recorder.py')"

echo.
echo [3/4] Installing necessary libraries (mss, pillow, requests, numpy, imageio)...
"!PY_EXE!" -m pip install mss requests truststore pillow numpy imageio imageio-ffmpeg --quiet --no-warn-script-location

echo.
echo [4/4] Setting up Windows Auto-Startup on PC Boot...

:: 1. Add to Windows Registry Run with FULL ABSOLUTE PATH to pythonw (never fails with 'cannot find pythonw')
reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "AlbayanStudyMonitorClient" /t REG_SZ /d "\"!PYW_EXE!\" \"%TARGET_DIR%\\client\\recorder.py\"" /f >nul

:: 2. Also add to Windows Startup Folder as VBScript (Dual redundancy, guaranteed silent on boot)
set "VBS_FILE=%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\StudyMonitorClient.vbs"
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WshShell.Run Chr^(34^) ^& "!PYW_EXE!" ^& Chr^(34^) ^& " " ^& Chr^(34^) ^& "%TARGET_DIR%\\client\\recorder.py" ^& Chr^(34^), 0, False
) > "!VBS_FILE!" 2>nul

echo.
echo Launching Screen Monitor in Background...
start "" "!PYW_EXE!" "%TARGET_DIR%\\client\\recorder.py"

echo.
echo ========================================================
echo   [SUCCESS] SETUP COMPLETE!
echo   - Screen Monitor is active in the background.
echo   - Whenever this PC is powered ON, it will start automatically!
echo ========================================================
echo.
pause
"""
    return Response(
        content=script_content,
        media_type="application/bat",
        headers={"Content-Disposition": "attachment; filename=albayan_setup.bat"}
    )

@app.get("/api/download/AlbayanMonitor.exe")
def download_albayan_monitor_exe(request: Request = None):
    upstream = get_upstream_url(request)
    if upstream:
        from fastapi.responses import RedirectResponse
        try:
            return RedirectResponse(url=f"{upstream}/api/download/AlbayanMonitor.exe")
        except Exception:
            pass

    cand_paths = [
        ROOT_DIR / "dist" / "AlbayanMonitor.exe",
        ROOT_DIR.parent / "dist" / "AlbayanMonitor.exe",
        ROOT_DIR / "client" / "AlbayanMonitor.exe"
    ]
    for p in cand_paths:
        if p.exists():
            return FileResponse(
                p,
                media_type="application/vnd.microsoft.portable-executable",
                filename="AlbayanMonitor.exe"
            )
    raise HTTPException(status_code=404, detail="AlbayanMonitor.exe not found on cloud node")

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
    if token and is_valid_session_token(token):
        return HTMLResponse(get_html_dashboard())
    return HTMLResponse(get_html_login())
