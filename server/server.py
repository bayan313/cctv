# -*- coding: utf-8 -*-
import os
import sys
import io
import json
import time
import socket
import asyncio
import secrets
import hmac
import hashlib
import zipfile
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
import html

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import requests
from fastapi import FastAPI, Request, Response, HTTPException, Depends, UploadFile, File, Form, Header, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyCookie
import uvicorn
from PIL import Image, ImageDraw, ImageFont

# Directories & Configuration
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
RECORDINGS_DIR = BASE_DIR / "server" / "recordings"
STATIC_DIR = BASE_DIR / "server" / "static"
CLIENT_DIR = BASE_DIR / "client"

try:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

DEFAULT_PC_NAMES = ["albayan 1", "albayan 2", "albayan 3", "albayan 4"]

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

def get_pc_screenshots(pc_name: str):
    clean = normalize_pc_name(pc_name)
    prefix = f"[{clean}]"
    if not RECORDINGS_DIR.exists():
        return []
    return sorted(
        [f for f in RECORDINGS_DIR.iterdir() if f.name.startswith(prefix) and f.suffix.lower() == ".jpg"],
        key=lambda f: f.stat().st_mtime
    )

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        # Dynamically sync detected LAN IP with config.json
        cfg = load_config()
        if cfg.get("server_ip") != ip:
            cfg["server_ip"] = ip
            save_config(cfg)
        return ip
    except Exception:
        return '127.0.0.1'

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

config = load_config()

# App State
SESSIONS_PATH = BASE_DIR / "server" / ".sessions.json"

def load_sessions() -> set:
    if SESSIONS_PATH.exists():
        try:
            with open(SESSIONS_PATH, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def save_sessions(sessions: set):
    try:
        with open(SESSIONS_PATH, "w", encoding="utf-8") as f:
            json.dump(list(sessions), f)
    except Exception:
        pass

active_sessions = load_sessions()
active_computers: Dict[str, Dict[str, Any]] = {}
last_cleanup_time = 0

SESSION_HMAC_SECRET = "secure_study_monitor_secret_key_8899"

def create_session_token() -> str:
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    cfg = load_config()
    pw = cfg.get("admin_password", "albayan@2026")
    msg = f"{ts}:{nonce}:{pw}"
    sig = hmac.new(SESSION_HMAC_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
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
    cfg = load_config()
    pw = cfg.get("admin_password", "albayan@2026")
    msg = f"{ts}:{nonce}:{pw}"
    expected_sig = hmac.new(SESSION_HMAC_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected_sig)

cookie_scheme = APIKeyCookie(name="session_token", auto_error=False)

def verify_session(session_token: Optional[str] = Depends(cookie_scheme)):
    if not session_token or not is_valid_session_token(session_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return session_token

def send_telegram_message(text: str):
    cfg = load_config()
    token = cfg.get("telegram_bot_token")
    chat_ids = cfg.get("telegram_chat_ids", [])
    if not token or not chat_ids:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for cid in chat_ids:
        try:
            r = requests.post(url, json={"chat_id": cid, "text": text, "parse_mode": "HTML"}, timeout=10)
            if r.status_code != 200:
                requests.post(url, json={"chat_id": cid, "text": text}, timeout=10)
        except Exception as e:
            print(f"[Telegram] Error sending message: {e}")

def send_telegram_photo(photo_path: Path, caption: str):
    cfg = load_config()
    token = cfg.get("telegram_bot_token")
    chat_ids = cfg.get("telegram_chat_ids", [])
    if not token or not chat_ids or not photo_path.exists():
        return
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    for cid in chat_ids:
        try:
            with open(photo_path, "rb") as pf:
                r = requests.post(
                    url,
                    data={"chat_id": cid, "caption": caption, "parse_mode": "HTML"},
                    files={"photo": (photo_path.name, pf, "image/jpeg")},
                    timeout=30
                )
                if r.status_code != 200:
                    pf.seek(0)
                    requests.post(
                        url,
                        data={"chat_id": cid, "caption": caption},
                        files={"photo": (photo_path.name, pf, "image/jpeg")},
                        timeout=30
                    )
        except Exception as e:
            print(f"[Telegram] Error sending photo: {e}")

def send_telegram_video(video_path: Path, caption: str):
    cfg = load_config()
    if not cfg.get("send_videos_to_telegram", True):
        return
    token = cfg.get("telegram_bot_token")
    chat_ids = cfg.get("telegram_chat_ids", [])
    if not token or not chat_ids or not video_path.exists():
        return
    url = f"https://api.telegram.org/bot{token}/sendVideo"
    for cid in chat_ids:
        try:
            with open(video_path, "rb") as vf:
                r = requests.post(
                    url,
                    data={"chat_id": cid, "caption": caption, "parse_mode": "HTML"},
                    files={"video": (video_path.name, vf, "video/mp4")},
                    timeout=120
                )
                if r.status_code != 200:
                    print(f"[Telegram] sendVideo failed ({r.status_code}): {r.text}")
                    vf.seek(0)
                    requests.post(
                        url,
                        data={"chat_id": cid, "caption": caption},
                        files={"video": (video_path.name, vf, "video/mp4")},
                        timeout=120
                    )
        except Exception as e:
            print(f"[Telegram] Error sending video: {e}")

# ----------------- PLACEHOLDER CCTV IMAGE GENERATOR -----------------

def generate_no_signal_image(computer_name: str) -> bytes:
    """Generates a retro CCTV 'NO SIGNAL' image when camera is offline."""
    w, h = 960, 540
    img = Image.new("RGB", (w, h), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)

    # Grid lines to mimic CCTV monitor
    for y in range(0, h, 20):
        draw.line([(0, y), (w, y)], fill=(20, 30, 50), width=1)

    # Box
    draw.rectangle([(80, 80), (w - 80, h - 80)], outline=(51, 65, 85), width=2)

    # Text overlay
    cam_id = "01"
    for idx, name in enumerate(DEFAULT_PC_NAMES):
        if name.lower() == computer_name.lower():
            cam_id = f"0{idx+1}"

    draw.text((100, 100), f"CAM {cam_id} // {computer_name.upper()}", fill=(100, 116, 139))
    draw.text((w // 2 - 130, h // 2 - 30), "[ NO LIVE SIGNAL ]", fill=(239, 68, 68))
    draw.text((w // 2 - 190, h // 2 + 10), "COMPUTER OFFLINE OR READY TO CONNECT", fill=(148, 163, 184))
    draw.text((100, h - 120), "STATUS: STANDBY", fill=(71, 85, 105))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()

# ----------------- BACKGROUND TASKS -----------------

async def auto_updater_task():
    await asyncio.sleep(15)
    print("[AutoUpdater] Safe GitHub update checker active.")
    while True:
        try:
            loop = asyncio.get_event_loop()
            def run_git_check():
                subprocess.run(["git", "fetch", "origin", "main"], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=20)
                res_status = subprocess.run(["git", "status", "-uno"], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=10)
                if "Your branch is behind" in res_status.stdout:
                    print("[AutoUpdater] Update found on GitHub! Safely pulling...")
                    subprocess.run(["git", "pull", "--no-rebase", "origin", "main"], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=30)
                    return True
                return False

            has_update = await loop.run_in_executor(None, run_git_check)
            if has_update:
                send_telegram_message("🔄 *System Update:* Server updated to latest version from GitHub.")
        except Exception:
            pass

        await asyncio.sleep(1800)

async def telegram_bot_poller():
    last_update_id = 0
    print("[Telegram] Bot listener active.")
    while True:
        try:
            cfg = load_config()
            token = cfg.get("telegram_bot_token")
            if not token:
                await asyncio.sleep(5)
                continue

            url = f"https://api.telegram.org/bot{token}/getUpdates"
            params = {"offset": last_update_id + 1, "timeout": 10}
            
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: requests.get(url, params=params, timeout=15))
            
            if resp.status_code == 200:
                data = resp.json()
                for update in data.get("result", []):
                    last_update_id = update["update_id"]
                    msg = update.get("message")
                    if not msg:
                        continue
                    
                    chat = msg.get("chat", {})
                    chat_id = chat.get("id")
                    text = msg.get("text", "").strip()
                    first_name = chat.get("first_name", "Parent")

                    if not chat_id:
                        continue

                    chat_ids = cfg.get("telegram_chat_ids", [])
                    if chat_id not in chat_ids:
                        chat_ids.append(chat_id)
                        cfg["telegram_chat_ids"] = chat_ids
                        save_config(cfg)

                    parts = text.split()
                    cmd = parts[0].lower() if parts else ""

                    if cmd == "/start":
                        welcome_msg = (
                            f"👋 Hello {first_name}!\n\n"
                            "🛡️ *Albayan Lab CCTV Screen Monitor Bot Connected!*\n\n"
                            "You can monitor all 4 lab computers from here.\n\n"
                            "📌 *Commands:*\n"
                            "• `/status` - Check all computers\n"
                            "• `/cam1` or `/snap1` - Instant screenshot of albayan 1\n"
                            "• `/cam2` - Instant screenshot of albayan 2\n"
                            "• `/cam3` - Instant screenshot of albayan 3\n"
                            "• `/cam4` - Instant screenshot of albayan 4\n"
                            "• `/link` - Get Web CCTV Dashboard link"
                        )
                        send_telegram_message(welcome_msg)
                    
                    elif cmd == "/status":
                        now = time.time()
                        lines = ["🖥️ *Albayan CCTV Computers Status (4 PCs):*"]
                        for pc_name in DEFAULT_PC_NAMES:
                            data = active_computers.get(pc_name, {})
                            is_online = (now - data.get("last_ping", 0)) < 60
                            if is_online:
                                status_icon = "🟢 *Online (CCTV Active)*"
                            else:
                                ago = int((now - data.get("last_ping", 0)) / 60) if "last_ping" in data else None
                                status_icon = f"🔴 *Offline* ({ago}m ago)" if ago else "🔴 *Offline / Ready*"
                            lines.append(f"• *{pc_name}:* {status_icon}")
                        send_telegram_message("\n".join(lines))

                    elif cmd in ["/cam1", "/snap1", "/cam2", "/snap2", "/cam3", "/snap3", "/cam4", "/snap4", "/snap"]:
                        idx_map = {"/cam1": "albayan 1", "/snap1": "albayan 1",
                                   "/cam2": "albayan 2", "/snap2": "albayan 2",
                                   "/cam3": "albayan 3", "/snap3": "albayan 3",
                                   "/cam4": "albayan 4", "/snap4": "albayan 4"}
                        target_pc = idx_map.get(cmd, "albayan 1")
                        if cmd == "/snap" and len(parts) > 1:
                            target_pc = normalize_pc_name(" ".join(parts[1:]))

                        live_path = RECORDINGS_DIR / f"live_{target_pc}.jpg"
                        if live_path.exists():
                            now_str = datetime.now().strftime("%I:%M:%S %p")
                            send_telegram_photo(live_path, f"📸 *[{target_pc.upper()}]* Live CCTV Screenshot ({now_str})")
                        else:
                            # Try finding latest screenshot
                            shots = get_pc_screenshots(target_pc)
                            if shots:
                                send_telegram_photo(shots[-1], f"📸 *[{target_pc.upper()}]* Recent Screenshot")
                            else:
                                send_telegram_message(f"ℹ️ No screenshot available yet for {target_pc}.")

                    elif cmd in ["/showvideos", "/videos_on"]:
                        cfg = load_config()
                        cfg["send_videos_to_telegram"] = True
                        save_config(cfg)
                        send_telegram_message("📹 *Automatic Video Delivery Enabled:*\nScreen video recording clips will be sent directly to Telegram.")

                    elif cmd in ["/hidevideos", "/videos_off"]:
                        cfg = load_config()
                        cfg["send_videos_to_telegram"] = False
                        save_config(cfg)
                        send_telegram_message("🔇 *Automatic Video Delivery Muted:*\nVideo clips will be saved on server/web only.")

                    elif cmd in ["/link", "/web", "/url", "/portal"]:
                        cfg = load_config()
                        pub_url = cfg.get("public_web_url") or getattr(app.state, "public_web_url", None)
                        lan_ip = get_lan_ip()
                        port = cfg.get("server_port", 8899)
                        if pub_url:
                            send_telegram_message(f"🌐 *Albayan CCTV Real Web Portal:*\n{pub_url}\n\nPassword: `albayan@2026`\n📱 Open from anywhere on mobile or PC!")
                        else:
                            send_telegram_message(f"🌐 *CCTV Web Dashboard:*\nhttp://{lan_ip}:{port}\nPassword: `albayan@2026`")

        except Exception:
            pass

        await asyncio.sleep(3)

async def auto_delete_old_files():
    """Deletes screenshots & videos older than retention_hours (24 hours)."""
    global last_cleanup_time
    print("[Cleanup] 24-hour auto-cleaner active (Screenshots & Recordings).")
    while True:
        try:
            cfg = load_config()
            retention_seconds = cfg.get("retention_hours", 24) * 3600
            now = time.time()
            deleted_count = 0

            # Delete old 5-min screenshots and old videos
            for file_path in RECORDINGS_DIR.iterdir():
                if file_path.name.startswith("live_"):
                    continue # Keep live thumbnail
                if file_path.suffix.lower() in [".jpg", ".jpeg", ".mp4", ".png"]:
                    file_age = now - file_path.stat().st_mtime
                    if file_age > retention_seconds:
                        try:
                            file_path.unlink()
                            deleted_count += 1
                        except Exception:
                            pass

            if deleted_count > 0:
                print(f"[Cleanup] Auto-deleted {deleted_count} file(s) older than 24 hours.")
            last_cleanup_time = now
        except Exception:
            pass

        await asyncio.sleep(600)

async def start_cloudflare_tunnel_task(app: FastAPI):
    """Starts Cloudflare Tunnel automatically to expose CCTV server to Real Web."""
    cfg = load_config()
    if not cfg.get("enable_cloud_tunnel", True):
        return

    await asyncio.sleep(2)
    port = cfg.get("server_port", 8899)
    cloudflared_bin = BASE_DIR / "cloudflared.exe"

    if not cloudflared_bin.exists():
        import shutil
        sys_cf = shutil.which("cloudflared")
        if sys_cf:
            cloudflared_bin = Path(sys_cf)
        else:
            print("[Tunnel] Downloading cloudflared.exe for Real Web access...")
            try:
                import urllib.request
                url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
                urllib.request.urlretrieve(url, str(cloudflared_bin))
                print("[Tunnel] cloudflared.exe downloaded successfully!")
            except Exception as e:
                print(f"[Tunnel] Error downloading cloudflared: {e}")
                return

    cmd = [str(cloudflared_bin), "tunnel", "--url", f"http://127.0.0.1:{port}"]
    print(f"[Tunnel] Opening Cloudflare HTTPS Tunnel on port {port}...")

    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )
            app.state.tunnel_proc = proc

            import re, webbrowser
            url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
            public_url = None

            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore")
                match = url_pattern.search(text)
                if match and not public_url:
                    public_url = match.group(0)
                    app.state.public_web_url = public_url

                    # Save into config
                    cfg_current = load_config()
                    cfg_current["public_web_url"] = public_url
                    save_config(cfg_current)

                    print("\n" + "=" * 70)
                    print("  🎉 [REAL WEB ACTIVE] ALBAYAN CCTV LAB IS LIVE ONLINE!")
                    print("=" * 70)
                    print(f"  🌐 Real Web Portal URL: {public_url}")
                    print(f"  🔑 Master Passcode:     {cfg_current.get('admin_password', 'albayan@2026')}")
                    print("  📱 Open this link on your mobile phone or any PC anywhere!")
                    print("=" * 70 + "\n")

                    # Telegram alert
                    msg = (
                        f"🌐 <b>ALBAYAN CCTV IS LIVE ON THE REAL WEB!</b> 🌐\n\n"
                        f"🔗 <b>Web Portal:</b> {public_url}\n"
                        f"🔑 <b>Password:</b> <code>{cfg_current.get('admin_password', 'albayan@2026')}</code>\n\n"
                        f"📱 Open this link from anywhere in the world on mobile data to monitor all 4 cameras!"
                    )
                    send_telegram_message(msg)

                    # Open browser
                    try:
                        webbrowser.open(public_url)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Tunnel] Tunnel error: {e}")

        await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    t_tg = asyncio.create_task(telegram_bot_poller())
    t_clean = asyncio.create_task(auto_delete_old_files())
    t_up = asyncio.create_task(auto_updater_task())
    t_tunnel = asyncio.create_task(start_cloudflare_tunnel_task(app))
    yield
    t_tg.cancel()
    t_clean.cancel()
    t_up.cancel()
    t_tunnel.cancel()
    if hasattr(app.state, "tunnel_proc") and app.state.tunnel_proc:
        try:
            app.state.tunnel_proc.terminate()
        except Exception:
            pass

# App Instance with Lifespan
app = FastAPI(title="Albayan CCTV Lab Monitor Portal", lifespan=lifespan)
if STATIC_DIR.exists():
    try:
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    except Exception:
        pass

# ----------------- CLIENT AUTO REGISTRATION -----------------

@app.post("/api/client/register")
def register_client(request: Request, payload: dict):
    cfg = load_config()
    client_ip = request.client.host if request.client else "unknown"
    device_id = payload.get("device_id", client_ip).strip()

    registered = cfg.get("registered_devices", {})
    if device_id in registered:
        assigned_name = registered[device_id]
    else:
        used_names = set(registered.values())
        assigned_name = None
        for name in DEFAULT_PC_NAMES:
            if name not in used_names:
                assigned_name = name
                break
        if not assigned_name:
            assigned_name = f"albayan {len(registered) + 1}"

        registered[device_id] = assigned_name
        cfg["registered_devices"] = registered
        save_config(cfg)
        send_telegram_message(f"🎉 *New PC Configured:* `{assigned_name}` (IP: `{client_ip}`)")

    lan_ip = get_lan_ip()
    port = cfg.get("server_port", 8899)

    return {
        "ok": True,
        "computer_name": assigned_name,
        "server_url": f"http://{lan_ip}:{port}",
        "api_secret": cfg.get("api_secret", "secure_study_monitor_secret_key_8899"),
        "screenshot_interval_seconds": cfg.get("screenshot_interval_seconds", 300),
        "live_stream_interval_seconds": cfg.get("live_stream_interval_seconds", 5)
    }

# ----------------- DOWNLOAD ENDPOINTS -----------------

@app.get("/api/download/recorder.py")
def download_recorder_py():
    rec_file = CLIENT_DIR / "recorder.py"
    if rec_file.exists():
        return FileResponse(rec_file, media_type="text/x-python", filename="recorder.py")
    raise HTTPException(status_code=404, detail="recorder.py not found")

@app.get("/api/download/setup-script")
def download_setup_script(request: Request, session: str = Depends(verify_session)):
    lan_ip = get_lan_ip()
    cfg = load_config()
    port = cfg.get("server_port", 8899)
    host_header = request.headers.get("host")
    proto = request.headers.get("x-forwarded-proto", "https" if request.url.scheme == "https" else "http")

    pub_url = cfg.get("public_web_url") or getattr(app.state, "public_web_url", None)
    if pub_url:
        server_base = pub_url.rstrip("/")
    elif host_header and not host_header.startswith("127.0.0.1") and not host_header.startswith("localhost"):
        server_base = f"{proto}://{host_header}"
    else:
        server_base = f"http://{lan_ip}:{port}"

    script_content = f"""@echo off
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

echo [1/4] Downloading latest CCTV client from server...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('{server_base}/api/download/recorder.py', '%TARGET_DIR%\\client\\recorder.py')"

echo.
echo [2/4] Verifying Python and installing dependencies...
python -m pip install mss requests truststore pillow numpy --quiet

echo.
echo [3/4] Registering PC name (albayan 1, 2, 3, or 4)...
python -c "import urllib.request, json, uuid, os, pathlib; dev_id=str(uuid.getnode()); req=urllib.request.Request('{server_base}/api/client/register', data=json.dumps({{'device_id':dev_id}}).encode(), headers={{'Content-Type':'application/json'}}); res=urllib.request.urlopen(req); data=json.loads(res.read().decode()); t_dir=pathlib.Path(os.environ.get('TARGET_DIR', '')); (t_dir / 'client' / 'client_config.json').write_text(json.dumps(data, indent=2), encoding='utf-8'); print('>> Successfully registered as: ' + data.get('computer_name', 'albayan'))"

echo.
echo [4/4] Setting up Windows Auto-Startup (HKCU Run)...
reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "AlbayanStudyMonitorClient" /t REG_SZ /d "pythonw \"%TARGET_DIR%\\client\\recorder.py\"" /f >nul

echo.
echo Starting Screen Monitor in Background...
start "" pythonw "%TARGET_DIR%\\client\\recorder.py"

echo.
echo ========================================================
echo   [SUCCESS] INSTALLED SUCCESSFULLY!
echo   This PC is now active and transmitting to CCTV!
echo ========================================================
echo.
pause
"""
    return Response(
        content=script_content,
        media_type="application/bat",
        headers={"Content-Disposition": "attachment; filename=albayan_cctv_setup.bat"}
    )

@app.get("/api/download/client-zip")
def download_client_zip(session: str = Depends(verify_session)):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        rec_path = CLIENT_DIR / "recorder.py"
        install_bat = BASE_DIR / "INSTALL_CLIENT.bat"
        cfg_path = BASE_DIR / "config.json"
        
        if rec_path.exists():
            zf.write(rec_path, arcname="client/recorder.py")
        if install_bat.exists():
            zf.write(install_bat, arcname="INSTALL_CLIENT.bat")
        if cfg_path.exists():
            zf.write(cfg_path, arcname="config.json")

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=albayan_cctv_monitor.zip"}
    )

# ----------------- CLIENT DATA INGESTION -----------------

@app.get("/api/ping")
def ping_health():
    return {"ok": True, "status": "online"}

@app.post("/api/client/ping")
def client_ping(
    request: Request,
    x_api_secret: Optional[str] = Header(None),
    payload: dict = {}
):
    cfg = load_config()
    if x_api_secret != cfg.get("api_secret"):
        raise HTTPException(status_code=403, detail="Forbidden")

    client_ip = request.client.host if request.client else "unknown"
    raw_name = payload.get("computer_name", "albayan 1")
    pc_name = normalize_pc_name(raw_name)

    now = time.time()
    is_new = pc_name not in active_computers or (now - active_computers[pc_name].get("last_ping", 0)) > 180
    
    if pc_name not in active_computers:
        active_computers[pc_name] = {}
    active_computers[pc_name]["last_ping"] = now
    active_computers[pc_name]["ip"] = client_ip

    if is_new:
        now_str = datetime.now().strftime("%I:%M:%S %p")
        send_telegram_message(f"🚨 <b>[{html.escape(pc_name.upper())}]</b> Turned ON and CCTV Screen Monitoring started at <b>{now_str}</b> (IP: <code>{client_ip}</code>).")

    return {
        "ok": True,
        "status": "active",
        "config": {
            "video_fps": cfg.get("video_fps", 10),
            "video_chunk_minutes": cfg.get("video_chunk_minutes", 2),
            "video_recording_enabled": cfg.get("video_recording_enabled", True),
            "live_stream_interval_seconds": cfg.get("live_stream_interval_seconds", 5),
            "screenshot_interval_seconds": cfg.get("screenshot_interval_seconds", 300)
        }
    }

@app.post("/api/client/live_frame")
async def client_live_frame(
    request: Request,
    frame: UploadFile = File(...),
    computer_name: str = Form("albayan 1"),
    x_api_secret: Optional[str] = Header(None)
):
    cfg = load_config()
    if x_api_secret != cfg.get("api_secret"):
        raise HTTPException(status_code=403, detail="Forbidden")

    pc_name = normalize_pc_name(computer_name)
    client_ip = request.client.host if request.client else "unknown"
    
    if pc_name not in active_computers:
        active_computers[pc_name] = {}
    active_computers[pc_name]["last_ping"] = time.time()
    active_computers[pc_name]["last_live"] = time.time()
    active_computers[pc_name]["ip"] = client_ip

    dest_path = RECORDINGS_DIR / f"live_{pc_name}.jpg"
    with open(dest_path, "wb") as f:
        while chunk := await frame.read(1024 * 128):
            f.write(chunk)

    return {"ok": True}

@app.post("/api/client/upload_screenshot")
async def client_upload_screenshot(
    request: Request,
    screenshot: UploadFile = File(...),
    computer_name: str = Form("albayan 1"),
    timestamp: str = Form(""),
    x_api_secret: Optional[str] = Header(None)
):
    cfg = load_config()
    if x_api_secret != cfg.get("api_secret"):
        raise HTTPException(status_code=403, detail="Forbidden")

    pc_name = normalize_pc_name(computer_name)
    client_ip = request.client.host if request.client else "unknown"
    
    if pc_name not in active_computers:
        active_computers[pc_name] = {}
    active_computers[pc_name]["last_ping"] = time.time()
    active_computers[pc_name]["ip"] = client_ip

    dest_path = RECORDINGS_DIR / screenshot.filename
    with open(dest_path, "wb") as f:
        while chunk := await screenshot.read(1024 * 256):
            f.write(chunk)

    # Also duplicate as live thumbnail
    live_path = RECORDINGS_DIR / f"live_{pc_name}.jpg"
    try:
        import shutil
        shutil.copyfile(dest_path, live_path)
    except Exception:
        pass

    file_size_kb = round(dest_path.stat().st_size / 1024, 1)
    print(f"[Screenshot] [{pc_name}] Received 5-min snapshot: {dest_path.name} ({file_size_kb} KB)")

    return {"ok": True, "filename": dest_path.name}

@app.post("/api/client/upload_video")
@app.post("/api/client/upload")
async def client_upload_video(
    request: Request,
    video: UploadFile = File(...),
    computer_name: str = Form("albayan 1"),
    x_api_secret: Optional[str] = Header(None)
):
    cfg = load_config()
    if x_api_secret != cfg.get("api_secret", "secure_study_monitor_secret_key_8899"):
        raise HTTPException(status_code=403, detail="Forbidden")

    pc_name = normalize_pc_name(computer_name)
    client_ip = request.client.host if request.client else "unknown"

    if pc_name not in active_computers:
        active_computers[pc_name] = {}
    active_computers[pc_name]["last_ping"] = time.time()
    active_computers[pc_name]["ip"] = client_ip

    dest_path = RECORDINGS_DIR / video.filename
    with open(dest_path, "wb") as f:
        while chunk := await video.read(1024 * 1024):
            f.write(chunk)

    file_size_mb = round(dest_path.stat().st_size / (1024 * 1024), 2)
    print(f"[Video Upload] [{pc_name}] Received Video Clip: {dest_path.name} ({file_size_mb} MB)")

    # Send video automatically to Telegram
    if cfg.get("send_videos_to_telegram", True):
        now_str = datetime.now().strftime("%I:%M %p")
        caption = (
            f"📹 <b>[{html.escape(pc_name.upper())}] Screen Video Recording</b>\n"
            f"🕒 Time: {now_str}\n"
            f"📁 File: <code>{html.escape(dest_path.name)}</code>\n"
            f"📦 Size: {file_size_mb} MB"
        )
        threading.Thread(target=send_telegram_video, args=(dest_path, caption), daemon=True).start()

    return {"ok": True, "filename": dest_path.name}

@app.post("/api/client/boot_notify")
def client_boot_notify(payload: dict, request: Request, x_api_secret: Optional[str] = Header(None)):
    cfg = load_config()
    if x_api_secret != cfg.get("api_secret", "secure_study_monitor_secret_key_8899"):
        raise HTTPException(status_code=403, detail="Forbidden")

    pc_name = normalize_pc_name(payload.get("computer_name", "albayan 1"))
    client_ip = request.client.host if request.client else "unknown"
    now_str = datetime.now().strftime("%I:%M:%S %p")

    print(f"[Boot Notify] [{pc_name}] Computer turned ON at {now_str} (IP: {client_ip})")
    send_telegram_message(
        f"🚨 <b>[{html.escape(pc_name.upper())}] Computer Turned ON!</b>\n"
        f"🕒 Time: <b>{now_str}</b>\n"
        f"🌐 IP: <code>{client_ip}</code>\n"
        f"📹 Automatic screen video recording & CCTV live stream started."
    )
    return {"ok": True}

# ----------------- CCTV IMAGE & STREAM API -----------------

@app.get("/api/live/{computer_name}")
def get_live_frame(computer_name: str):
    pc_name = normalize_pc_name(computer_name)
    live_path = RECORDINGS_DIR / f"live_{pc_name}.jpg"

    if live_path.exists():
        return FileResponse(
            live_path,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

    # Check if any recent snapshot exists for this PC
    shots = get_pc_screenshots(pc_name)
    if shots:
        return FileResponse(
            shots[-1],
            media_type="image/jpeg",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

    # Fallback to no-signal CCTV test pattern only if no image exists
    content = generate_no_signal_image(pc_name)
    return Response(
        content=content,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )

@app.get("/api/screenshots")
def get_screenshots(
    computer: str = Query("albayan 1"),
    session: str = Depends(verify_session)
):
    pc_name = normalize_pc_name(computer)
    files = get_pc_screenshots(pc_name)
    results = []

    now = time.time()
    for f in files:
        mtime = f.stat().st_mtime
        age_hours = (now - mtime) / 3600
        if age_hours > 24:
            continue
        
        # parse timestamp from filename: [albayan 1]_YYYYMMDD_HHMMSS.jpg
        name = f.name
        try:
            ts_part = name.split("]_")[1].replace(".jpg", "")
            dt = datetime.strptime(ts_part, "%Y%m%d_%H%M%S")
            time_label = dt.strftime("%I:%M %p")
            date_label = dt.strftime("%b %d, %Y")
            full_str = dt.strftime("%Y-%m-%d %I:%M:%S %p")
        except Exception:
            full_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %I:%M:%S %p")
            time_label = datetime.fromtimestamp(mtime).strftime("%I:%M %p")
            date_label = ""

        results.append({
            "filename": f.name,
            "computer": pc_name,
            "url": f"/api/screenshot/{f.name}",
            "time_label": time_label,
            "date_label": date_label,
            "created_at": full_str,
            "timestamp": mtime,
            "size_kb": round(f.stat().st_size / 1024, 1)
        })

    return {
        "computer": pc_name,
        "total": len(results),
        "screenshots": results
    }

@app.get("/api/screenshot/{filename}")
def serve_screenshot(filename: str):
    safe_name = Path(filename).name
    path = RECORDINGS_DIR / safe_name
    if path.exists() and path.suffix.lower() in [".jpg", ".jpeg", ".png"]:
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
    raise HTTPException(status_code=404, detail="Screenshot not found")

# ----------------- SYSTEM STATUS & AUTH -----------------

@app.get("/api/status")
def get_system_status(session: str = Depends(verify_session)):
    cfg = load_config()
    chat_ids = cfg.get("telegram_chat_ids", [])
    now = time.time()
    
    computers_list = []
    online_count = 0

    for pc_name in DEFAULT_PC_NAMES:
        data = active_computers.get(pc_name, {})
        live_file = RECORDINGS_DIR / f"live_{pc_name}.jpg"
        live_age = (now - live_file.stat().st_mtime) if live_file.exists() else 999999
        ping_age = (now - data.get("last_ping", 0)) if "last_ping" in data else 999999
        last_seen_sec = min(live_age, ping_age)
        is_online = last_seen_sec < 90

        if is_online:
            online_count += 1

        shots_count = len(get_pc_screenshots(pc_name))
        computers_list.append({
            "name": pc_name,
            "is_online": is_online,
            "ip": data.get("ip", "Offline / Ready"),
            "snapshots_count": shots_count,
            "last_seen_seconds": int(last_seen_sec) if last_seen_sec < 86400 else None
        })

    all_shots = list(RECORDINGS_DIR.glob("*.jpg"))
    total_size_bytes = sum(f.stat().st_size for f in all_shots)
    lan_ip = get_lan_ip()
    port = cfg.get("server_port", 8899)
    pub_url = cfg.get("public_web_url") or getattr(app.state, "public_web_url", "")
    
    return {
        "server_ip": lan_ip,
        "server_port": port,
        "public_web_url": pub_url,
        "computers": computers_list,
        "total_online": online_count,
        "total_snapshots": len([f for f in all_shots if not f.name.startswith("live_")]),
        "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
        "telegram_connected": len(chat_ids) > 0,
        "retention_hours": cfg.get("retention_hours", 24)
    }

@app.post("/api/login")
@app.post("/login")
def login(payload: dict, request: Request, response: Response):
    password = payload.get("password")
    cfg = load_config()
    expected_password = cfg.get("admin_password", "albayan@2026")
    if password == expected_password:
        token = create_session_token()
        active_sessions.add(token)
        save_sessions(active_sessions)
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
        save_sessions(active_sessions)
    response.delete_cookie("session_token", path="/")
    return {"ok": True}

@app.get("/api/settings")
def get_settings(session: str = Depends(verify_session)):
    cfg = load_config()
    return {
        "retention_hours": cfg.get("retention_hours", 24),
        "video_fps": cfg.get("video_fps", 10),
        "video_chunk_minutes": cfg.get("video_chunk_minutes", 2),
        "send_videos_to_telegram": cfg.get("send_videos_to_telegram", True),
        "video_recording_enabled": cfg.get("video_recording_enabled", True),
        "live_stream_interval_seconds": cfg.get("live_stream_interval_seconds", 5),
        "screenshot_interval_seconds": cfg.get("screenshot_interval_seconds", 300),
        "admin_password": cfg.get("admin_password", "albayan@2026")
    }

@app.post("/api/settings")
def update_settings(payload: dict, session: str = Depends(verify_session)):
    cfg = load_config()
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

    save_config(cfg)
    print(f"[Settings] Updated configuration: retention={cfg.get('retention_hours')}h, fps={cfg.get('video_fps')}, chunk={cfg.get('video_chunk_minutes')}m, telegram={cfg.get('send_videos_to_telegram')}")
    return {"ok": True, "message": "Settings updated successfully"}

# ----------------- WEB PAGES (CCTV INTERFACE) -----------------

@app.get("/", response_class=HTMLResponse)
@app.get("/api", response_class=HTMLResponse)
@app.get("/api/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/cctv", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def index_page(request: Request, session_token: Optional[str] = Depends(cookie_scheme)):
    if not session_token or not is_valid_session_token(session_token):
        return get_login_html()
    return get_cctv_dashboard_html()

def get_login_html():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Albayan CCTV Monitor - Login</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
</head>
<body class="bg-slate-950 flex items-center justify-center min-h-screen p-4 text-slate-100">
  <div class="w-full max-w-md bg-slate-900 border border-slate-800 rounded-3xl p-8 shadow-2xl relative overflow-hidden">
    <div class="absolute -right-12 -top-12 w-40 h-40 bg-indigo-600/10 rounded-full blur-3xl pointer-events-none"></div>
    <div class="text-center mb-8">
      <div class="w-16 h-16 bg-gradient-to-tr from-indigo-600 to-emerald-500 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-lg shadow-indigo-600/30 text-white text-2xl">
        <i class="fa-solid fa-video"></i>
      </div>
      <h1 class="text-2xl font-bold tracking-tight text-white">Albayan CCTV Lab</h1>
      <p class="text-xs text-slate-400 mt-1">4-Screen Surveillance & Study Monitor</p>
    </div>

    <form id="loginForm" class="space-y-4">
      <div>
        <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Master Password</label>
        <div class="relative">
          <input 
            type="password" 
            id="password" 
            placeholder="••••••••••••" 
            required
            class="w-full bg-slate-950 border border-slate-700/80 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition"
          >
          <span class="absolute right-4 top-3 text-slate-500"><i class="fa-solid fa-lock"></i></span>
        </div>
      </div>

      <div id="loginError" class="hidden text-xs text-rose-400 bg-rose-500/10 border border-rose-500/20 rounded-xl p-3 text-center"></div>

      <button 
        type="submit" 
        class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-3 rounded-xl transition text-sm shadow-lg shadow-indigo-600/30 flex items-center justify-center gap-2"
      >
        <span>Open CCTV Dashboard</span>
        <i class="fa-solid fa-arrow-right text-xs"></i>
      </button>
    </form>

    <div class="mt-8 pt-6 border-t border-slate-800/80 text-center text-[11px] text-slate-500">
      <p>Albayan Computer Lab • 24-Hour Auto-Purge</p>
    </div>
  </div>

  <script>
    document.getElementById('loginForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const pwd = document.getElementById('password').value;
      const err = document.getElementById('loginError');
      err.classList.add('hidden');
      try {
        const res = await fetch('/api/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: pwd })
        });
        if (res.ok) {
          window.location.reload();
        } else {
          err.innerText = 'Incorrect password! Please try again.';
          err.classList.remove('hidden');
        }
      } catch (e) {
        err.innerText = 'Connection error. Please try again.';
        err.classList.remove('hidden');
      }
    });
  </script>
</body>
</html>"""

def get_cctv_dashboard_html():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Albayan CCTV Monitor - 4 Camera Grid</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
  <style>
    @keyframes pulse-slow {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.4; transform: scale(0.95); }
    }
    .pulse-rec {
      animation: pulse-slow 1.5s infinite ease-in-out;
    }
    .cctv-scanline {
      background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%);
      background-size: 100% 4px;
    }
    .osd-font {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col font-sans select-none">

  <!-- Top CCTV Command Header -->
  <header class="border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-md sticky top-0 z-40">
    <div class="max-w-7xl mx-auto px-3 sm:px-6 h-16 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 bg-emerald-600 rounded-xl flex items-center justify-center text-white text-lg shadow-md shadow-emerald-600/30">
          <i class="fa-solid fa-video"></i>
        </div>
        <div>
          <div class="flex items-center gap-2">
            <h1 class="text-base sm:text-lg font-bold text-white tracking-tight">ALBAYAN CCTV LAB</h1>
            <span class="bg-red-500/20 text-red-400 text-[10px] font-mono px-2 py-0.5 rounded border border-red-500/30 flex items-center gap-1">
              <span class="w-1.5 h-1.5 rounded-full bg-red-500 pulse-rec"></span> LIVE DVR
            </span>
          </div>
          <p class="text-[11px] text-slate-400">4-Camera Surveillance & 5-Min History Scrubber</p>
        </div>
      </div>

      <!-- Controls & Setup button -->
      <div class="flex items-center gap-2 sm:gap-3">
        <a href="/api/download/setup-script" download="albayan_setup.bat" class="hidden sm:flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg shadow-md transition">
          <i class="fa-solid fa-cloud-arrow-down"></i>
          <span>1-Click PC Installer</span>
        </a>

        <div class="hidden md:flex items-center gap-2 bg-emerald-500/10 px-3 py-1.5 rounded-lg border border-emerald-500/30 text-xs">
          <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span class="text-slate-400">WEB:</span>
          <span id="serverIpBadge" class="text-emerald-400 font-mono font-semibold">REAL WEB ONLINE</span>
        </div>

        <a href="https://t.me/my_library_data_bot" target="_blank" class="bg-sky-600/20 hover:bg-sky-600/30 text-sky-400 text-xs px-2.5 py-1.5 rounded-lg border border-sky-500/30 transition flex items-center gap-1.5">
          <i class="fa-brands fa-telegram"></i>
          <span class="hidden sm:inline">Bot</span>
        </a>

        <button onclick="openSettingsModal()" class="text-xs text-amber-300 hover:text-white bg-amber-500/20 hover:bg-amber-500/30 px-3 py-1.5 rounded-lg border border-amber-500/30 transition flex items-center gap-1.5 font-semibold shadow-sm">
          <i class="fa-solid fa-sliders"></i>
          <span>Settings</span>
        </button>

        <button onclick="logout()" class="text-xs text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 px-3 py-1.5 rounded-lg border border-slate-700 transition flex items-center gap-1.5">
          <i class="fa-solid fa-arrow-right-from-bracket"></i>
          <span class="hidden sm:inline">Logout</span>
        </button>
      </div>
    </div>
  </header>

  <!-- View Switcher & Toolbar -->
  <div class="bg-slate-900/60 border-b border-slate-800/80 px-4 py-2.5">
    <div class="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-3">
      <!-- Camera Selection Tabs -->
      <div class="flex items-center gap-1.5 bg-slate-950/80 p-1 rounded-xl border border-slate-800 text-xs">
        <button id="btnViewQuad" onclick="setViewMode('quad')" class="px-3 py-1.5 rounded-lg font-semibold bg-indigo-600 text-white shadow transition flex items-center gap-1.5">
          <i class="fa-solid fa-table-cells-large"></i> <span>QUAD VIEW (4 CAM)</span>
        </button>
        <button id="btnViewCam1" onclick="setViewMode('albayan 1')" class="px-2.5 py-1.5 rounded-lg font-medium text-slate-400 hover:text-white hover:bg-slate-800/60 transition">
          CAM 1
        </button>
        <button id="btnViewCam2" onclick="setViewMode('albayan 2')" class="px-2.5 py-1.5 rounded-lg font-medium text-slate-400 hover:text-white hover:bg-slate-800/60 transition">
          CAM 2
        </button>
        <button id="btnViewCam3" onclick="setViewMode('albayan 3')" class="px-2.5 py-1.5 rounded-lg font-medium text-slate-400 hover:text-white hover:bg-slate-800/60 transition">
          CAM 3
        </button>
        <button id="btnViewCam4" onclick="setViewMode('albayan 4')" class="px-2.5 py-1.5 rounded-lg font-medium text-slate-400 hover:text-white hover:bg-slate-800/60 transition">
          CAM 4
        </button>
      </div>

      <!-- Quick Status Badges -->
      <div class="flex items-center gap-3 text-xs">
        <span id="activeCamBadge" class="text-emerald-400 bg-emerald-500/10 px-2.5 py-1 rounded-full border border-emerald-500/20 font-semibold flex items-center gap-1.5">
          <span class="w-2 h-2 rounded-full bg-emerald-400"></span> <span id="onlineCountText">0 Online</span>
        </span>
        <span class="hidden sm:inline-block text-slate-500 font-mono text-[11px]">
          <i class="fa-solid fa-clock-rotate-left mr-1"></i> Auto-wipe: 24h
        </span>
      </div>
    </div>
  </div>

  <!-- CCTV Main Workspace -->
  <main class="max-w-7xl mx-auto px-2 sm:px-4 py-4 sm:py-6 flex-1 w-full">
    
    <!-- 2x2 CCTV Grid Container -->
    <div id="cctvGrid" class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- 4 Camera Panels generated dynamically -->
    </div>

  </main>

  <!-- Fullscreen Modal Viewer -->
  <div id="fullscreenModal" class="fixed inset-0 z-50 bg-black/95 hidden flex flex-col p-4 justify-between">
    <div class="flex items-center justify-between text-white border-b border-slate-800 pb-2">
      <div class="flex items-center gap-2">
        <span id="modalCamTitle" class="font-mono text-emerald-400 font-bold text-sm">CAM 01 // ALBAYAN 1</span>
        <span id="modalCamStatus" class="text-xs bg-red-600/30 text-red-300 px-2 py-0.5 rounded font-mono">LIVE</span>
      </div>
      <button onclick="closeFullscreen()" class="text-slate-400 hover:text-white text-lg px-3 py-1 bg-slate-800 rounded-lg">
        <i class="fa-solid fa-xmark"></i> Close
      </button>
    </div>
    <div class="flex-1 flex items-center justify-center p-2 relative">
      <img id="modalImg" class="max-h-[85vh] max-w-full rounded border border-slate-800 shadow-2xl object-contain" src="" alt="Fullscreen Feed">
    </div>
  </div>

  <!-- Settings Modal -->
  <div id="settingsModal" class="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm hidden flex items-center justify-center p-3 sm:p-6 overflow-y-auto">
    <div class="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-2xl p-5 sm:p-6 text-slate-100 shadow-2xl space-y-5 my-auto max-h-[90vh] overflow-y-auto">
      
      <!-- Modal Header -->
      <div class="flex items-center justify-between border-b border-slate-800 pb-4 sticky top-0 bg-slate-900 z-10">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-amber-500/20 text-amber-400 flex items-center justify-center text-lg border border-amber-500/30">
            <i class="fa-solid fa-sliders"></i>
          </div>
          <div>
            <h2 class="text-base sm:text-lg font-bold text-white">CCTV & Recording Settings</h2>
            <p class="text-[11px] text-slate-400">റെക്കോർഡിംഗ്, ഫ്രെയിംറേറ്റ് & സൂക്ഷിക്കേണ്ട സമയം ക്രമീകരിക്കുക</p>
          </div>
        </div>
        <button type="button" onclick="closeSettingsModal()" class="text-slate-400 hover:text-white text-xl p-1.5 rounded-lg hover:bg-slate-800 transition">
          <i class="fa-solid fa-xmark"></i>
        </button>
      </div>

      <!-- Settings Form -->
      <form id="settingsForm" onsubmit="saveSettings(event)" class="space-y-4 text-xs">
        
        <!-- Grid 2-col -->
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          
          <!-- 1. Retention Hours -->
          <div class="space-y-1.5 bg-slate-950/60 p-3.5 rounded-xl border border-slate-800/80">
            <label class="block font-semibold text-slate-300 flex items-center gap-1.5">
              <i class="fa-solid fa-trash-can-clock text-rose-400"></i> Video Retention (സൂക്ഷിക്കേണ്ട സമയം)
            </label>
            <select id="cfg_retention_hours" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-slate-200 focus:outline-none focus:border-amber-500">
              <option value="6">6 Hours (6 മണിക്കൂർ)</option>
              <option value="12">12 Hours (12 മണിക്കൂർ)</option>
              <option value="24">24 Hours (1 Day - Default)</option>
              <option value="48">48 Hours (2 Days)</option>
              <option value="72">72 Hours (3 Days)</option>
              <option value="168">7 Days (1 Week)</option>
              <option value="720">30 Days (1 Month)</option>
            </select>
            <p class="text-[10px] text-slate-500">ഇത്രയും മണിക്കൂർ കഴിഞ്ഞ വീഡിയോകളും സ്ക്രീൻഷോട്ടുകളും സ്വയം ഡിലീറ്റ് ചെയ്യപ്പെടും.</p>
          </div>

          <!-- 2. Video FPS -->
          <div class="space-y-1.5 bg-slate-950/60 p-3.5 rounded-xl border border-slate-800/80">
            <label class="block font-semibold text-slate-300 flex items-center gap-1.5">
              <i class="fa-solid fa-gauge-high text-sky-400"></i> Frame Rate (Per Second എത്ര Frame)
            </label>
            <select id="cfg_video_fps" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-slate-200 focus:outline-none focus:border-amber-500">
              <option value="5">5 FPS (Ultra Light - കുറഞ്ഞ ഫയൽ സൈസ് & CPU)</option>
              <option value="10">10 FPS (Recommended - Balanced & Smooth)</option>
              <option value="15">15 FPS (High Quality)</option>
              <option value="20">20 FPS (Ultra Smooth)</option>
            </select>
            <p class="text-[10px] text-slate-500">വീഡിയോയുടെ സ്മൂത്ത്‌നെസ്സ്. 10 FPS സാധാരണ ആവശ്യങ്ങൾക്ക് ഏറ്റവും അനുയോജ്യമാണ്.</p>
          </div>

          <!-- 3. Video Chunk Duration -->
          <div class="space-y-1.5 bg-slate-950/60 p-3.5 rounded-xl border border-slate-800/80">
            <label class="block font-semibold text-slate-300 flex items-center gap-1.5">
              <i class="fa-solid fa-clock text-emerald-400"></i> Video Clip Duration (ക്ലിപ്പ് ദൈർഘ്യം)
            </label>
            <select id="cfg_video_chunk_minutes" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-slate-200 focus:outline-none focus:border-amber-500">
              <option value="1">1 Minute (ഓരോ 1 മിനിറ്റ് ക്ലിപ്പുകൾ)</option>
              <option value="2">2 Minutes (Default / Recommended)</option>
              <option value="5">5 Minutes</option>
              <option value="10">10 Minutes</option>
            </select>
            <p class="text-[10px] text-slate-500">ഓരോ വീഡിയോയും എത്ര മിനിറ്റ് വീതമുള്ള ക്ലിപ്പുകളായി സൂക്ഷിക്കണം.</p>
          </div>

          <!-- 4. Live Stream Refresh -->
          <div class="space-y-1.5 bg-slate-950/60 p-3.5 rounded-xl border border-slate-800/80">
            <label class="block font-semibold text-slate-300 flex items-center gap-1.5">
              <i class="fa-solid fa-arrows-rotate text-purple-400"></i> Live Stream Rate (CCTV ലൈവ് വേഗത)
            </label>
            <select id="cfg_live_stream_interval" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-slate-200 focus:outline-none focus:border-amber-500">
              <option value="2">Every 2 Seconds (Fast Realtime)</option>
              <option value="3">Every 3 Seconds</option>
              <option value="5">Every 5 Seconds (Recommended)</option>
              <option value="10">Every 10 Seconds (Low Data)</option>
            </select>
            <p class="text-[10px] text-slate-500">ഡാഷ്‌ബോർഡ് ലൈവ് ക്യാമറ സ്ക്രീൻ പുതുക്കേണ്ട ഇടവേള.</p>
          </div>

          <!-- 5. 5-Min Screenshot Interval -->
          <div class="space-y-1.5 bg-slate-950/60 p-3.5 rounded-xl border border-slate-800/80">
            <label class="block font-semibold text-slate-300 flex items-center gap-1.5">
              <i class="fa-solid fa-camera text-indigo-400"></i> Timeline Snapshot Interval
            </label>
            <select id="cfg_screenshot_interval" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-slate-200 focus:outline-none focus:border-amber-500">
              <option value="60">Every 1 Minute (1 മിനിറ്റ് കൂടുമ്പോൾ)</option>
              <option value="180">Every 3 Minutes (3 മിനിറ്റ് കൂടുമ്പോൾ)</option>
              <option value="300">Every 5 Minutes (5 മിനിറ്റ് - Default)</option>
              <option value="600">Every 10 Minutes (10 മിനിറ്റ് കൂടുമ്പോൾ)</option>
            </select>
            <p class="text-[10px] text-slate-500">ടൈംലൈനിലേക്ക് സ്ക്രീൻഷോട്ട് സേവ് ചെയ്യേണ്ട ഇടവേള.</p>
          </div>

          <!-- 6. Admin Password -->
          <div class="space-y-1.5 bg-slate-950/60 p-3.5 rounded-xl border border-slate-800/80">
            <label class="block font-semibold text-slate-300 flex items-center gap-1.5">
              <i class="fa-solid fa-key text-yellow-400"></i> Admin Passcode (പാസ്‌വേഡ് മാറ്റം)
            </label>
            <input type="text" id="cfg_admin_password" class="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-slate-200 font-mono focus:outline-none focus:border-amber-500" placeholder="albayan@2026">
            <p class="text-[10px] text-slate-500">ഡാഷ്‌ബോർഡ് ലോഗിൻ ചെയ്യാനുള്ള മാസ്റ്റർ പാസ്‌വേഡ്.</p>
          </div>

        </div>

        <!-- Toggles Section -->
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
          
          <!-- Send to Telegram Toggle -->
          <div class="flex items-center justify-between p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl">
            <div>
              <div class="font-semibold text-white flex items-center gap-1.5">
                <i class="fa-brands fa-telegram text-sky-400"></i> Send Videos to Telegram
              </div>
              <div class="text-[10px] text-slate-400">വീഡിയോ ക്ലിപ്പുകൾ ബോട്ടിലേക്ക് അയക്കുക</div>
            </div>
            <label class="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" id="cfg_send_videos_to_telegram" class="sr-only peer">
              <div class="w-11 h-6 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-600"></div>
            </label>
          </div>

          <!-- Video Recording Enabled Toggle -->
          <div class="flex items-center justify-between p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl">
            <div>
              <div class="font-semibold text-white flex items-center gap-1.5">
                <i class="fa-solid fa-circle-dot text-rose-500 pulse-rec"></i> Video Recording Active
              </div>
              <div class="text-[10px] text-slate-400">കമ്പ്യൂട്ടറുകളിൽ വീഡിയോ റെക്കോർഡിംഗ്</div>
            </div>
            <label class="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" id="cfg_video_recording_enabled" class="sr-only peer">
              <div class="w-11 h-6 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-600"></div>
            </label>
          </div>

        </div>

        <!-- Alert Notice -->
        <div id="settingsNotice" class="hidden p-2.5 rounded-lg text-center font-medium"></div>

        <!-- Footer Buttons -->
        <div class="flex items-center justify-end gap-3 pt-4 border-t border-slate-800">
          <button type="button" onclick="closeSettingsModal()" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl font-medium transition">
            Cancel
          </button>
          <button type="submit" id="btnSaveSettings" class="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold rounded-xl transition flex items-center gap-2 shadow-lg shadow-emerald-600/30">
            <i class="fa-solid fa-floppy-disk"></i>
            <span>Save Settings</span>
          </button>
        </div>

      </form>
    </div>
  </div>

  <script>
    const CAM_NAMES = ["albayan 1", "albayan 2", "albayan 3", "albayan 4"];
    let currentViewMode = "quad"; // "quad" or specific pc name
    let camStates = {}; // Stores live vs history mode, playback index, screenshots array
    let autoPlayTimers = {};

    CAM_NAMES.forEach((name, idx) => {
      camStates[name] = {
        mode: "live", // "live" or "history"
        historyIndex: 0,
        screenshots: [],
        isPlaying: false,
        lastLiveUrl: `/api/live/${encodeURIComponent(name)}?t=${Date.now()}`
      };
    });

    // ----------------- RENDER CCTV CAMERAS -----------------

    function initCCTVGrid() {
      const grid = document.getElementById("cctvGrid");
      grid.innerHTML = "";

      CAM_NAMES.forEach((camName, idx) => {
        const camId = `0${idx + 1}`;
        const panel = document.createElement("div");
        panel.id = `panel_${camName.replace(' ', '_')}`;
        panel.className = "bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-2xl flex flex-col transition";

        panel.innerHTML = `
          <!-- Camera Header Bar -->
          <div class="bg-slate-950/90 px-3 sm:px-4 py-2 border-b border-slate-800 flex items-center justify-between text-xs">
            <div class="flex items-center gap-2 font-mono">
              <span class="bg-slate-800 text-slate-300 px-2 py-0.5 rounded font-bold">CH ${camId}</span>
              <span class="text-white font-semibold uppercase tracking-wider">${camName}</span>
              <span id="badge_status_${idx}" class="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-400">
                OFFLINE
              </span>
            </div>

            <div class="flex items-center gap-2">
              <span id="clock_${idx}" class="font-mono text-emerald-400 text-[11px] hidden sm:inline">--:--:--</span>
              <button onclick="toggleFullscreen('${camName}')" title="Fullscreen" class="text-slate-400 hover:text-white p-1">
                <i class="fa-solid fa-expand"></i>
              </button>
            </div>
          </div>

          <!-- Screen Canvas with CCTV OSD -->
          <div class="relative bg-black aspect-video flex items-center justify-center overflow-hidden group">
            <img 
              id="img_${idx}" 
              src="/api/live/${encodeURIComponent(camName)}" 
              alt="${camName} Screen" 
              class="w-full h-full object-contain"
            />
            
            <!-- Retro OSD Scanlines & Labels -->
            <div class="absolute inset-0 pointer-events-none cctv-scanline opacity-30"></div>

            <!-- Top Left CCTV OSD -->
            <div class="absolute top-2 left-2 pointer-events-none font-mono text-[11px] text-emerald-400 drop-shadow-[0_1px_2px_rgba(0,0,0,0.9)] flex flex-col gap-0.5">
              <div class="flex items-center gap-1.5 font-bold">
                <span id="osd_rec_${idx}" class="w-2 h-2 rounded-full bg-red-500 pulse-rec"></span>
                <span id="osd_title_${idx}">REC [${camName.toUpperCase()}]</span>
              </div>
              <div id="osd_sub_${idx}" class="text-[10px] text-slate-300">5-MIN SNAPSHOT MODE</div>
            </div>

            <!-- Bottom Right CCTV OSD -->
            <div class="absolute bottom-2 right-2 pointer-events-none font-mono text-[10px] text-emerald-400 bg-black/60 px-2 py-0.5 rounded border border-emerald-500/20">
              <span id="osd_frame_info_${idx}">LIVE FEED</span>
            </div>
          </div>

          <!-- CCTV DVR Playback Toolbar (Directly beneath camera) -->
          <div class="bg-slate-950 px-3 py-2 border-t border-slate-800 flex flex-col gap-2">
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-1.5">
                <button 
                  id="btn_live_${idx}" 
                  onclick="setCamMode('${camName}', 'live')" 
                  class="px-2.5 py-1 rounded-lg text-xs font-semibold bg-emerald-600 text-white shadow transition flex items-center gap-1"
                >
                  <i class="fa-solid fa-circle text-[8px] text-white pulse-rec"></i> Live
                </button>
                <button 
                  id="btn_hist_${idx}" 
                  onclick="setCamMode('${camName}', 'history')" 
                  class="px-2.5 py-1 rounded-lg text-xs font-medium text-slate-400 hover:text-white bg-slate-800/80 hover:bg-slate-800 transition flex items-center gap-1"
                >
                  <i class="fa-solid fa-clock-rotate-left text-xs text-amber-400"></i> 5-Min Reel
                </button>
              </div>

              <!-- History Playback Controls (Visible only in History Mode) -->
              <div id="hist_controls_${idx}" class="hidden flex items-center gap-1">
                <button onclick="stepHistory('${camName}', -1)" title="Previous 5-Min Snapshot" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs rounded transition">
                  <i class="fa-solid fa-backward-step"></i>
                </button>
                <button id="btn_play_${idx}" onclick="togglePlayHistory('${camName}')" class="px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded transition flex items-center gap-1">
                  <i class="fa-solid fa-play text-[10px]"></i> Play
                </button>
                <button onclick="stepHistory('${camName}', 1)" title="Next 5-Min Snapshot" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs rounded transition">
                  <i class="fa-solid fa-forward-step"></i>
                </button>
              </div>

              <!-- Snapshot download -->
              <button onclick="downloadCurrentSnapshot('${camName}')" title="Download Full Snapshot" class="text-slate-400 hover:text-white bg-slate-800/60 hover:bg-slate-800 px-2 py-1 rounded text-xs transition">
                <i class="fa-solid fa-download"></i>
              </button>
            </div>

            <!-- Scrubber Slider for 5-Min History -->
            <div id="scrubber_container_${idx}" class="hidden pt-1 border-t border-slate-900 flex items-center gap-2">
              <input 
                id="slider_${idx}" 
                type="range" 
                min="0" 
                max="0" 
                value="0" 
                oninput="onScrubberSlide('${camName}', this.value)" 
                class="w-full accent-indigo-500 bg-slate-800 h-1.5 rounded cursor-pointer"
              />
              <span id="slider_label_${idx}" class="font-mono text-[10px] text-slate-400 shrink-0 w-28 text-right">00:00 AM</span>
            </div>
          </div>
        `;

        grid.appendChild(panel);
      });
    }

    // ----------------- LIVE CLOCK & UPDATE LOOPS -----------------

    function updateDigitalClocks() {
      const now = new Date();
      const timeStr = now.toLocaleTimeString();
      CAM_NAMES.forEach((_, idx) => {
        const el = document.getElementById(`clock_${idx}`);
        if (el) el.innerText = timeStr;
      });
    }
    setInterval(updateDigitalClocks, 1000);

    // Refresh live feeds seamlessly
    async function refreshLiveFeeds() {
      CAM_NAMES.forEach((camName, idx) => {
        const state = camStates[camName];
        if (state.mode === "live") {
          const imgEl = document.getElementById(`img_${idx}`);
          if (imgEl) {
            // Preload image off-screen to avoid flicker
            const tempImg = new Image();
            const newUrl = `/api/live/${encodeURIComponent(camName)}?t=${Date.now()}`;
            tempImg.src = newUrl;
            tempImg.onload = () => {
              if (state.mode === "live") {
                imgEl.src = newUrl;
                state.lastLiveUrl = newUrl;
              }
            };
          }
        }
      });
    }
    setInterval(refreshLiveFeeds, 3500);

    // Refresh system status from server
    async function refreshStatus() {
      try {
        const res = await fetch('/api/status');
        if (!res.ok) {
          if (res.status === 401) window.location.reload();
          return;
        }
        const data = await res.json();
        
        if (data.public_web_url) {
          document.getElementById('serverIpBadge').innerText = 'REAL WEB LIVE';
        } else if (window.location.protocol === 'https:' || !window.location.hostname.match(/^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$/)) {
          document.getElementById('serverIpBadge').innerText = 'REAL WEB LIVE';
        } else {
          document.getElementById('serverIpBadge').innerText = `${data.server_ip}:${data.server_port}`;
        }
        document.getElementById('onlineCountText').innerText = `${data.total_online} Online`;

        data.computers.forEach((pc, idx) => {
          const badge = document.getElementById(`badge_status_${idx}`);
          const recDot = document.getElementById(`osd_rec_${idx}`);
          if (badge) {
            if (pc.is_online) {
              badge.className = "text-[10px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-bold border border-emerald-500/30";
              badge.innerText = `ONLINE (${pc.ip})`;
              if (recDot) recDot.className = "w-2 h-2 rounded-full bg-red-500 pulse-rec";
            } else {
              badge.className = "text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-500";
              badge.innerText = "OFFLINE";
              if (recDot) recDot.className = "w-2 h-2 rounded-full bg-slate-600";
            }
          }
        });
      } catch (e) {
        console.error("Status error:", e);
      }
    }
    setInterval(refreshStatus, 4000);

    // ----------------- CCTV DVR HISTORY & SCRUBBER -----------------

    async function setCamMode(camName, mode) {
      const idx = CAM_NAMES.indexOf(camName);
      const state = camStates[camName];
      state.mode = mode;

      const btnLive = document.getElementById(`btn_live_${idx}`);
      const btnHist = document.getElementById(`btn_hist_${idx}`);
      const histControls = document.getElementById(`hist_controls_${idx}`);
      const scrubber = document.getElementById(`scrubber_container_${idx}`);
      const osdFrame = document.getElementById(`osd_frame_info_${idx}`);

      if (mode === "live") {
        btnLive.className = "px-2.5 py-1 rounded-lg text-xs font-semibold bg-emerald-600 text-white shadow transition flex items-center gap-1";
        btnHist.className = "px-2.5 py-1 rounded-lg text-xs font-medium text-slate-400 hover:text-white bg-slate-800/80 hover:bg-slate-800 transition flex items-center gap-1";
        histControls.classList.add("hidden");
        scrubber.classList.add("hidden");
        osdFrame.innerText = "LIVE FEED";
        
        // Stop any autoplay
        if (state.isPlaying) togglePlayHistory(camName);
        
        // Restore live image
        document.getElementById(`img_${idx}`).src = state.lastLiveUrl;
      } else {
        btnHist.className = "px-2.5 py-1 rounded-lg text-xs font-semibold bg-amber-600 text-white shadow transition flex items-center gap-1";
        btnLive.className = "px-2.5 py-1 rounded-lg text-xs font-medium text-slate-400 hover:text-white bg-slate-800/80 hover:bg-slate-800 transition flex items-center gap-1";
        histControls.classList.remove("hidden");
        scrubber.classList.remove("hidden");

        // Load 5-minute screenshots
        await loadCamScreenshots(camName);
      }
    }

    async function loadCamScreenshots(camName) {
      const idx = CAM_NAMES.indexOf(camName);
      const state = camStates[camName];
      const slider = document.getElementById(`slider_${idx}`);
      const sliderLabel = document.getElementById(`slider_label_${idx}`);

      try {
        const res = await fetch(`/api/screenshots?computer=${encodeURIComponent(camName)}`);
        const data = await res.json();
        state.screenshots = data.screenshots || [];

        if (state.screenshots.length > 0) {
          slider.max = state.screenshots.length - 1;
          slider.value = state.screenshots.length - 1; // Start at latest
          state.historyIndex = state.screenshots.length - 1;
          showHistoryFrame(camName, state.historyIndex);
        } else {
          slider.max = 0;
          slider.value = 0;
          sliderLabel.innerText = "No snapshots";
          document.getElementById(`osd_frame_info_${idx}`).innerText = "NO RECORDINGS (24h)";
        }
      } catch (e) {
        console.error("Error loading screenshots:", e);
      }
    }

    function showHistoryFrame(camName, frameIndex) {
      const idx = CAM_NAMES.indexOf(camName);
      const state = camStates[camName];
      if (!state.screenshots || state.screenshots.length === 0) return;

      const item = state.screenshots[frameIndex];
      if (!item) return;

      const imgEl = document.getElementById(`img_${idx}`);
      imgEl.src = item.url;

      const slider = document.getElementById(`slider_${idx}`);
      const sliderLabel = document.getElementById(`slider_label_${idx}`);
      const osdFrame = document.getElementById(`osd_frame_info_${idx}`);

      slider.value = frameIndex;
      sliderLabel.innerText = `${item.time_label} (${frameIndex + 1}/${state.screenshots.length})`;
      osdFrame.innerText = `PLAYBACK: ${item.created_at}`;
    }

    function onScrubberSlide(camName, value) {
      const state = camStates[camName];
      state.historyIndex = parseInt(value, 10);
      showHistoryFrame(camName, state.historyIndex);
    }

    function stepHistory(camName, delta) {
      const state = camStates[camName];
      if (!state.screenshots || state.screenshots.length === 0) return;
      let nextIdx = state.historyIndex + delta;
      if (nextIdx < 0) nextIdx = 0;
      if (nextIdx >= state.screenshots.length) nextIdx = state.screenshots.length - 1;
      state.historyIndex = nextIdx;
      showHistoryFrame(camName, nextIdx);
    }

    function togglePlayHistory(camName) {
      const idx = CAM_NAMES.indexOf(camName);
      const state = camStates[camName];
      const playBtn = document.getElementById(`btn_play_${idx}`);

      if (state.isPlaying) {
        clearInterval(autoPlayTimers[camName]);
        state.isPlaying = false;
        playBtn.innerHTML = '<i class="fa-solid fa-play text-[10px]"></i> Play';
        playBtn.className = "px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded transition flex items-center gap-1";
      } else {
        if (!state.screenshots || state.screenshots.length === 0) return;
        state.isPlaying = true;
        playBtn.innerHTML = '<i class="fa-solid fa-pause text-[10px]"></i> Pause';
        playBtn.className = "px-2.5 py-1 bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold rounded transition flex items-center gap-1";

        autoPlayTimers[camName] = setInterval(() => {
          if (state.historyIndex >= state.screenshots.length - 1) {
            state.historyIndex = 0; // Loop around
          } else {
            state.historyIndex += 1;
          }
          showHistoryFrame(camName, state.historyIndex);
        }, 600); // 1.6 frames per second smooth reel
      }
    }

    function downloadCurrentSnapshot(camName) {
      const idx = CAM_NAMES.indexOf(camName);
      const state = camStates[camName];
      let url = "";
      let filename = `${camName}_snapshot.jpg`;

      if (state.mode === "live") {
        url = `/api/live/${encodeURIComponent(camName)}`;
      } else if (state.screenshots && state.screenshots[state.historyIndex]) {
        url = state.screenshots[state.historyIndex].url;
        filename = state.screenshots[state.historyIndex].filename;
      }

      if (url) {
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }
    }

    // ----------------- VIEW MODES (QUAD vs SINGLE CAM) -----------------

    function setViewMode(mode) {
      currentViewMode = mode;
      
      const btnQuad = document.getElementById("btnViewQuad");
      const btnCams = [
        document.getElementById("btnViewCam1"),
        document.getElementById("btnViewCam2"),
        document.getElementById("btnViewCam3"),
        document.getElementById("btnViewCam4")
      ];

      btnQuad.className = "px-3 py-1.5 rounded-lg font-semibold text-slate-400 hover:text-white hover:bg-slate-800/60 transition";
      btnCams.forEach(b => b.className = "px-2.5 py-1.5 rounded-lg font-medium text-slate-400 hover:text-white hover:bg-slate-800/60 transition");

      if (mode === "quad") {
        btnQuad.className = "px-3 py-1.5 rounded-lg font-semibold bg-indigo-600 text-white shadow transition flex items-center gap-1.5";
        CAM_NAMES.forEach(camName => {
          const panel = document.getElementById(`panel_${camName.replace(' ', '_')}`);
          if (panel) panel.classList.remove("hidden");
        });
        const grid = document.getElementById("cctvGrid");
        grid.className = "grid grid-cols-1 lg:grid-cols-2 gap-4";
      } else {
        const activeIdx = CAM_NAMES.indexOf(mode);
        if (btnCams[activeIdx]) {
          btnCams[activeIdx].className = "px-2.5 py-1.5 rounded-lg font-semibold bg-indigo-600 text-white shadow transition";
        }
        CAM_NAMES.forEach(camName => {
          const panel = document.getElementById(`panel_${camName.replace(' ', '_')}`);
          if (panel) {
            if (camName.toLowerCase() === mode.toLowerCase()) {
              panel.classList.remove("hidden");
            } else {
              panel.classList.add("hidden");
            }
          }
        });
        const grid = document.getElementById("cctvGrid");
        grid.className = "grid grid-cols-1 gap-4 max-w-5xl mx-auto";
      }
    }

    // ----------------- FULLSCREEN VIEWER -----------------

    function toggleFullscreen(camName) {
      const idx = CAM_NAMES.indexOf(camName);
      const state = camStates[camName];
      const modal = document.getElementById("fullscreenModal");
      const modalImg = document.getElementById("modalImg");
      const title = document.getElementById("modalCamTitle");
      const status = document.getElementById("modalCamStatus");

      title.innerText = `CH 0${idx + 1} // ${camName.toUpperCase()}`;
      if (state.mode === "live") {
        modalImg.src = `/api/live/${encodeURIComponent(camName)}?t=${Date.now()}`;
        status.innerText = "LIVE STREAM";
      } else if (state.screenshots && state.screenshots[state.historyIndex]) {
        modalImg.src = state.screenshots[state.historyIndex].url;
        status.innerText = `PLAYBACK: ${state.screenshots[state.historyIndex].created_at}`;
      }

      modal.classList.remove("hidden");
    }

    function closeFullscreen() {
      document.getElementById("fullscreenModal").classList.add("hidden");
    }

    async function logout() {
      await fetch('/api/logout', { method: 'POST' });
      window.location.reload();
    }

    // ----------------- SETTINGS MODAL -----------------

    async function openSettingsModal() {
      const modal = document.getElementById("settingsModal");
      const notice = document.getElementById("settingsNotice");
      notice.classList.add("hidden");
      modal.classList.remove("hidden");
      try {
        const res = await fetch("/api/settings");
        if (res.ok) {
          const data = await res.json();
          document.getElementById("cfg_retention_hours").value = data.retention_hours || 24;
          document.getElementById("cfg_video_fps").value = data.video_fps || 10;
          document.getElementById("cfg_video_chunk_minutes").value = data.video_chunk_minutes || 2;
          document.getElementById("cfg_live_stream_interval").value = data.live_stream_interval_seconds || 5;
          document.getElementById("cfg_screenshot_interval").value = data.screenshot_interval_seconds || 300;
          document.getElementById("cfg_admin_password").value = data.admin_password || "albayan@2026";
          document.getElementById("cfg_send_videos_to_telegram").checked = data.send_videos_to_telegram !== false;
          document.getElementById("cfg_video_recording_enabled").checked = data.video_recording_enabled !== false;
        }
      } catch (e) {
        console.error("Error loading settings:", e);
      }
    }

    function closeSettingsModal() {
      document.getElementById("settingsModal").classList.add("hidden");
      const notice = document.getElementById("settingsNotice");
      notice.classList.add("hidden");
    }

    async function saveSettings(e) {
      e.preventDefault();
      const notice = document.getElementById("settingsNotice");
      const btn = document.getElementById("btnSaveSettings");
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving...';

      const payload = {
        retention_hours: parseInt(document.getElementById("cfg_retention_hours").value),
        video_fps: parseInt(document.getElementById("cfg_video_fps").value),
        video_chunk_minutes: parseInt(document.getElementById("cfg_video_chunk_minutes").value),
        live_stream_interval_seconds: parseInt(document.getElementById("cfg_live_stream_interval").value),
        screenshot_interval_seconds: parseInt(document.getElementById("cfg_screenshot_interval").value),
        admin_password: document.getElementById("cfg_admin_password").value.trim() || "albayan@2026",
        send_videos_to_telegram: document.getElementById("cfg_send_videos_to_telegram").checked,
        video_recording_enabled: document.getElementById("cfg_video_recording_enabled").checked
      };

      try {
        const res = await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          notice.className = "p-2.5 rounded-lg text-center font-medium bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
          notice.innerHTML = "✅ Settings saved successfully! All PCs will auto-sync within 20s.";
          notice.classList.remove("hidden");
          setTimeout(() => {
            closeSettingsModal();
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> <span>Save Settings</span>';
          }, 1500);
        } else {
          const err = await res.json();
          notice.className = "p-2.5 rounded-lg text-center font-medium bg-rose-500/20 text-rose-400 border border-rose-500/30";
          notice.innerText = "❌ Error: " + (err.detail || "Failed to save settings");
          notice.classList.remove("hidden");
          btn.disabled = false;
          btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> <span>Save Settings</span>';
        }
      } catch (err) {
        notice.className = "p-2.5 rounded-lg text-center font-medium bg-rose-500/20 text-rose-400 border border-rose-500/30";
        notice.innerText = "❌ Network error while saving settings";
        notice.classList.remove("hidden");
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> <span>Save Settings</span>';
      }
    }

    // Boot
    window.addEventListener("DOMContentLoaded", () => {
      initCCTVGrid();
      refreshStatus();
      updateDigitalClocks();
    });
  </script>
</body>
</html>"""

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    path = request.url.path
    if path.startswith("/api/") and not any(path.startswith(p) for p in ["/api/login", "/api/logout", "/api/download"]):
        return JSONResponse(status_code=404, content={"detail": f"Route {path} not found"})
    token = request.cookies.get("session_token")
    if token and is_valid_session_token(token):
        return HTMLResponse(get_cctv_dashboard_html())
    return HTMLResponse(get_login_html())

if __name__ == "__main__":
    lan_ip = get_lan_ip()
    port = config.get("server_port", 8899)
    print("=" * 65)
    print("  ALBAYAN CCTV LAB MONITOR - 4 CAMERAS REAL WEB SERVER")
    print("=" * 65)
    print(f" Real Web Status:   Connecting Cloudflare HTTPS Tunnel...")
    print(f" Master Passcode:   albayan@2026")
    print(f" Monitored PCs:     albayan 1, albayan 2, albayan 3, albayan 4")
    print(f" Capture Mode:      5-Min Screenshots (CCTV Timeline Reel)")
    print(f" Live Feed:         CCTV Quad Screen (every 3-5 seconds)")
    print("=" * 65)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
