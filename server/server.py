# -*- coding: utf-8 -*-
import os
import sys
import io
import json
import time
import socket
import asyncio
import secrets
import zipfile
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import requests
from fastapi import FastAPI, Request, Response, HTTPException, Depends, UploadFile, File, Form, Header, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyCookie
import uvicorn

# Directories & Configuration
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
RECORDINGS_DIR = BASE_DIR / "server" / "recordings"
STATIC_DIR = BASE_DIR / "server" / "static"
CLIENT_DIR = BASE_DIR / "client"

RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

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

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

config = load_config()

# App State
app = FastAPI(title="Albayan Study Monitor Portal")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

active_sessions = set()
active_computers: Dict[str, Dict[str, Any]] = {}
last_cleanup_time = 0

cookie_scheme = APIKeyCookie(name="session_token", auto_error=False)

def verify_session(session_token: Optional[str] = Depends(cookie_scheme)):
    if not session_token or session_token not in active_sessions:
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
            requests.post(url, json={"chat_id": cid, "text": text, "parse_mode": "Markdown"}, timeout=5)
        except Exception:
            pass

def send_telegram_video(video_path: Path, caption: str):
    cfg = load_config()
    if not cfg.get("send_videos_to_telegram", False):
        return
    token = cfg.get("telegram_bot_token")
    chat_ids = cfg.get("telegram_chat_ids", [])
    if not token or not chat_ids:
        return
    url = f"https://api.telegram.org/bot{token}/sendVideo"
    for cid in chat_ids:
        try:
            with open(video_path, "rb") as vf:
                requests.post(
                    url,
                    data={"chat_id": cid, "caption": caption, "parse_mode": "Markdown"},
                    files={"video": vf},
                    timeout=45
                )
        except Exception:
            pass

# ----------------- AUTO UPDATER -----------------

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

# ----------------- TELEGRAM & CLEANUP TASKS -----------------

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
                            "🛡️ *Albayan Lab Study Monitor Bot Connected!*\n\n"
                            "You can monitor all 4 lab computers (albayan 1, 2, 3, 4) from here.\n\n"
                            "📌 *Commands:*\n"
                            "• `/status` - Check all computers\n"
                            "• `/hidevideos` - Hide videos from Telegram (keeps chat clean)\n"
                            "• `/showvideos` - Enable video sending to Telegram\n"
                            "• `/latest <albayan 1>` - View latest recording\n"
                            "• `/link` - Get Web Dashboard link"
                        )
                        send_telegram_message(welcome_msg)
                    
                    elif cmd == "/status":
                        now = time.time()
                        lines = ["🖥️ *Albayan Computers Status (4 PCs):*"]
                        for pc_name in DEFAULT_PC_NAMES:
                            data = active_computers.get(pc_name, {})
                            is_online = (now - data.get("last_ping", 0)) < 60
                            if is_online:
                                status_icon = "🟢 *Online (Recording 2-min clips)*"
                            else:
                                ago = int((now - data.get("last_ping", 0)) / 60) if "last_ping" in data else None
                                status_icon = f"🔴 *Offline* ({ago}m ago)" if ago else "🔴 *Offline / Ready*"
                            lines.append(f"• *{pc_name}:* {status_icon}")
                        send_telegram_message("\n".join(lines))

                    elif cmd in ["/hidevideos", "/mutevideos"]:
                        cfg["send_videos_to_telegram"] = False
                        save_config(cfg)
                        send_telegram_message("🔇 *Videos Hidden from Telegram:*\nVideos will not flood Telegram. They remain saved on the Web Dashboard.")

                    elif cmd in ["/showvideos", "/unmutevideos"]:
                        cfg["send_videos_to_telegram"] = True
                        save_config(cfg)
                        send_telegram_message("📹 *Videos Enabled in Telegram:*\nNew clips will be sent here.")

                    elif cmd == "/link":
                        lan_ip = get_lan_ip()
                        port = cfg.get("server_port", 8899)
                        send_telegram_message(f"🌐 *Web Dashboard URL:*\nhttp://{lan_ip}:{port}\nPassword: `albayan@2026`")

                    elif cmd == "/latest":
                        target_pc = " ".join(parts[1:]).strip().lower() if len(parts) > 1 else None
                        files = sorted(RECORDINGS_DIR.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
                        if target_pc:
                            files = [f for f in files if f.name.lower().startswith(f"[{target_pc}]")]
                        
                        if files:
                            latest_file = files[0]
                            caption = f"📹 Latest recording: `{latest_file.name}`"
                            cfg_token = cfg.get("telegram_bot_token")
                            with open(latest_file, "rb") as vf:
                                requests.post(
                                    f"https://api.telegram.org/bot{cfg_token}/sendVideo",
                                    data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
                                    files={"video": vf},
                                    timeout=45
                                )
                        else:
                            msg = f"ℹ️ No recordings found" + (f" for {target_pc}" if target_pc else "") + " in the last 24h."
                            send_telegram_message(msg)

        except Exception:
            pass

        await asyncio.sleep(3)

async def auto_delete_old_recordings():
    """Deletes recordings older than retention_hours (24 hours)."""
    global last_cleanup_time
    print("[Cleanup] 24-hour auto-cleaner active.")
    while True:
        try:
            cfg = load_config()
            retention_seconds = cfg.get("retention_hours", 24) * 3600
            now = time.time()
            deleted_count = 0

            for file_path in RECORDINGS_DIR.glob("*.mp4"):
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

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(telegram_bot_poller())
    asyncio.create_task(auto_delete_old_recordings())
    asyncio.create_task(auto_updater_task())

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
        "fps": cfg.get("fps", 10),
        "chunk_minutes": cfg.get("chunk_minutes", 2)
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
    port = load_config().get("server_port", 8899)
    host_header = request.headers.get("host")
    server_base = f"http://{host_header}" if host_header else f"http://{lan_ip}:{port}"

    script_content = f"""@echo off
setlocal
title Albayan Study Monitor - Auto Installer
echo ========================================================
echo   ALBAYAN LAB MONITOR - 1-CLICK CLIENT INSTALLER
echo ========================================================
echo.

set TARGET_DIR=%LOCALAPPDATA%\\AlbayanMonitor
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
if not exist "%TARGET_DIR%\\client" mkdir "%TARGET_DIR%\\client"
if not exist "%TARGET_DIR%\\client\\temp_records" mkdir "%TARGET_DIR%\\client\\temp_records"

echo [1/4] Downloading latest software from server...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('{server_base}/api/download/recorder.py', '%TARGET_DIR%\\client\\recorder.py')"

echo.
echo [2/4] Verifying Python and installing dependencies...
python -m pip install mss imageio imageio-ffmpeg requests truststore pillow --quiet

echo.
echo [3/4] Registering PC name (albayan 1, 2, 3, or 4)...
python -c "import urllib.request, json, uuid; dev_id=str(uuid.getnode()); req=urllib.request.Request('{server_base}/api/client/register', data=json.dumps({{'device_id':dev_id}}).encode(), headers={{'Content-Type':'application/json'}}); res=urllib.request.urlopen(req); data=json.loads(res.read().decode()); open(r'%TARGET_DIR%\\client\\client_config.json', 'w').write(json.dumps(data, indent=2)); print('>> Successfully registered as: ' + data.get('computer_name', 'albayan'))"

echo.
echo [4/4] Setting up Windows Auto-Startup...
set STARTUP_DIR=%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup
set VBS_FILE=%STARTUP_DIR%\\StudyMonitorLauncher.vbs
echo Set WshShell = CreateObject("WScript.Shell") > "%VBS_FILE%"
echo WshShell.Run ""pythonw "" ^& ""%TARGET_DIR%\\client\\recorder.py"" , 0, False >> "%VBS_FILE%"

echo.
echo Starting Screen Monitor in Background...
start "" pythonw "%TARGET_DIR%\\client\\recorder.py"

echo.
echo ========================================================
echo   [SUCCESS] INSTALLED SUCCESSFULLY!
echo   This PC is now active and monitored!
echo ========================================================
echo.
pause
"""
    return Response(
        content=script_content,
        media_type="application/bat",
        headers={"Content-Disposition": "attachment; filename=albayan_setup.bat"}
    )

@app.get("/api/download/client-zip")
def download_client_zip(session: str = Depends(verify_session)):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        rec_path = CLIENT_DIR / "recorder.py"
        one_click = BASE_DIR / "ONE_CLICK_INSTALL.bat"
        cfg_path = BASE_DIR / "config.json"
        
        if rec_path.exists():
            zf.write(rec_path, arcname="client/recorder.py")
        if one_click.exists():
            zf.write(one_click, arcname="ONE_CLICK_INSTALL.bat")
        if cfg_path.exists():
            zf.write(cfg_path, arcname="config.json")

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=albayan_monitor_full.zip"}
    )

# ----------------- WEB ROUTES -----------------

@app.get("/", response_class=HTMLResponse)
def index_page(request: Request, session_token: Optional[str] = Depends(cookie_scheme)):
    if not session_token or session_token not in active_sessions:
        return get_login_html()
    return get_dashboard_html()

@app.post("/api/login")
def login(payload: dict, response: Response):
    password = payload.get("password")
    cfg = load_config()
    expected_password = cfg.get("admin_password", "albayan@2026")
    if password == expected_password:
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
def logout(response: Response, session_token: Optional[str] = Depends(cookie_scheme)):
    if session_token in active_sessions:
        active_sessions.remove(session_token)
    response.delete_cookie("session_token")
    return {"ok": True}

@app.get("/api/status")
def get_system_status(session: str = Depends(verify_session)):
    cfg = load_config()
    chat_ids = cfg.get("telegram_chat_ids", [])
    now = time.time()
    
    # Strictly return the 4 Albayan Computers - no duplicates!
    computers_list = []
    online_count = 0

    for pc_name in DEFAULT_PC_NAMES:
        data = active_computers.get(pc_name, {})
        is_online = (now - data.get("last_ping", 0)) < 60
        if is_online:
            online_count += 1
        computers_list.append({
            "name": pc_name,
            "is_online": is_online,
            "ip": data.get("ip", "Offline / Ready"),
            "last_seen_seconds": int(now - data.get("last_ping", 0)) if "last_ping" in data else None
        })

    files = list(RECORDINGS_DIR.glob("*.mp4"))
    total_size_bytes = sum(f.stat().st_size for f in files)
    lan_ip = get_lan_ip()
    port = cfg.get("server_port", 8899)
    
    return {
        "server_ip": lan_ip,
        "server_port": port,
        "computers": computers_list,
        "total_online": online_count,
        "total_recordings": len(files),
        "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
        "telegram_connected": len(chat_ids) > 0,
        "telegram_videos_enabled": cfg.get("send_videos_to_telegram", False),
        "retention_hours": cfg.get("retention_hours", 24)
    }

@app.get("/api/recordings")
def list_recordings(
    computer: Optional[str] = Query(None),
    session: str = Depends(verify_session)
):
    files = sorted(RECORDINGS_DIR.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
    results = []
    now = time.time()
    
    for f in files:
        name = f.name
        raw_name = "albayan 1"
        if name.startswith("[") and "]" in name:
            raw_name = name[1:name.find("]")]
        
        pc_name = normalize_pc_name(raw_name)

        if computer and computer != "all":
            # Compare whitespace/case-insensitively
            target = computer.replace(" ", "").lower()
            item_pc = pc_name.replace(" ", "").lower()
            if target != item_pc:
                continue

        mtime = f.stat().st_mtime
        size_mb = round(f.stat().st_size / (1024 * 1024), 2)
        created_dt = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %I:%M:%S %p")
        age_hours = round((now - mtime) / 3600, 1)
        hours_remaining = round(max(0, 24 - age_hours), 1)

        results.append({
            "filename": f.name,
            "computer": pc_name,
            "created_at": created_dt,
            "size_mb": size_mb,
            "hours_remaining": hours_remaining
        })

    return {"recordings": results, "all_computers": DEFAULT_PC_NAMES}

@app.delete("/api/recordings/{filename}")
def delete_recording(filename: str, session: str = Depends(verify_session)):
    safe_name = Path(filename).name
    file_path = RECORDINGS_DIR / safe_name
    if file_path.exists():
        file_path.unlink()
        return {"ok": True, "message": "File deleted"}
    raise HTTPException(status_code=404, detail="File not found")

@app.get("/api/video/{filename}")
def stream_video(filename: str, request: Request, session_token: Optional[str] = Depends(cookie_scheme)):
    if not session_token or session_token not in active_sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")

    safe_name = Path(filename).name
    file_path = RECORDINGS_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    file_size = file_path.stat().st_size
    range_header = request.headers.get("Range")

    if range_header:
        parts = range_header.replace("bytes=", "").split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
        end = min(end, file_size - 1)
        chunk_size = end - start + 1

        def iterfile():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = chunk_size
                while remaining > 0:
                    read_bytes = min(remaining, 64 * 1024)
                    data = f.read(read_bytes)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size),
            "Content-Type": "video/mp4",
        }
        return StreamingResponse(iterfile(), status_code=206, headers=headers)

    def full_iter():
        with open(file_path, "rb") as f:
            while chunk := f.read(64 * 1024):
                yield chunk

    return StreamingResponse(full_iter(), media_type="video/mp4")

# ----------------- CLIENT ENDPOINTS -----------------

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
    is_new = pc_name not in active_computers or (now - active_computers[pc_name]["last_ping"]) > 180
    active_computers[pc_name] = {"last_ping": now, "ip": client_ip}

    if is_new:
        now_str = datetime.now().strftime("%I:%M:%S %p")
        send_telegram_message(f"🚨 *[{pc_name}]* Turned ON and Screen Monitoring started at *{now_str}* (IP: `{client_ip}`).")

    return {"ok": True, "status": "active"}

@app.post("/api/client/upload")
async def client_upload(
    request: Request,
    video: UploadFile = File(...),
    computer_name: str = Form("albayan 1"),
    x_api_secret: Optional[str] = Header(None)
):
    cfg = load_config()
    if x_api_secret != cfg.get("api_secret"):
        raise HTTPException(status_code=403, detail="Forbidden")

    pc_name = normalize_pc_name(computer_name)
    client_ip = request.client.host if request.client else "unknown"
    active_computers[pc_name] = {"last_ping": time.time(), "ip": client_ip}

    dest_path = RECORDINGS_DIR / video.filename
    with open(dest_path, "wb") as f:
        while chunk := await video.read(1024 * 1024):
            f.write(chunk)

    file_size_mb = round(dest_path.stat().st_size / (1024 * 1024), 2)
    print(f"[Upload] [{pc_name}] Received 2-minute video: {dest_path.name} ({file_size_mb} MB)")

    if cfg.get("send_videos_to_telegram", False):
        caption = f"📹 *[{pc_name}] Screen Recording*\nFile: `{dest_path.name}`\nSize: {file_size_mb} MB"
        send_telegram_video(dest_path, caption)

    return {"ok": True, "filename": dest_path.name}

# ----------------- HTML TEMPLATES -----------------

def get_login_html():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Albayan Lab Study Monitor - Login</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex items-center justify-center p-4">
  <div class="w-full max-w-md bg-slate-900/90 border border-slate-800 rounded-2xl p-8 shadow-2xl backdrop-blur-xl">
    <div class="text-center mb-8">
      <div class="w-16 h-16 bg-gradient-to-tr from-indigo-500 to-cyan-400 rounded-2xl mx-auto flex items-center justify-center text-3xl shadow-lg shadow-indigo-500/20 mb-4">
        <i class="fa-solid fa-graduation-cap text-white"></i>
      </div>
      <h1 class="text-2xl font-bold tracking-tight text-white">Albayan Study Monitor</h1>
      <p class="text-sm text-slate-400 mt-1">Multi-PC Screen Archive (albayan 1, 2, 3, 4)</p>
    </div>

    <form id="loginForm" class="space-y-5">
      <div>
        <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Master Password</label>
        <div class="relative">
          <input type="password" id="password" required placeholder="Enter password (albayan@2026)..." 
            class="w-full bg-slate-950/70 border border-slate-800 rounded-xl px-4 py-3 pl-11 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all">
          <i class="fa-solid fa-lock absolute left-4 top-3.5 text-slate-500"></i>
        </div>
      </div>

      <div id="errorMsg" class="hidden text-xs text-rose-400 bg-rose-500/10 border border-rose-500/20 rounded-lg p-3 text-center"></div>

      <button type="submit" 
        class="w-full bg-gradient-to-r from-indigo-600 to-cyan-600 hover:from-indigo-500 hover:to-cyan-500 text-white font-semibold py-3 px-4 rounded-xl shadow-lg shadow-indigo-600/25 transition-all duration-200 flex items-center justify-center gap-2">
        <span>Unlock Lab Dashboard</span>
        <i class="fa-solid fa-arrow-right"></i>
      </button>
    </form>

    <div class="mt-8 pt-6 border-t border-slate-800/80 text-center text-xs text-slate-500">
      <p><i class="fa-solid fa-clock-rotate-left mr-1"></i> Auto-deletion active: Videos kept for 24 hours</p>
    </div>
  </div>

  <script>
    document.getElementById('loginForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const pwd = document.getElementById('password').value;
      const err = document.getElementById('errorMsg');
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

def get_dashboard_html():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Albayan Lab Study Monitor</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
  <!-- Top Navigation -->
  <header class="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md sticky top-0 z-30">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 bg-indigo-600 rounded-xl flex items-center justify-center text-white text-lg shadow-md shadow-indigo-600/30">
          <i class="fa-solid fa-graduation-cap"></i>
        </div>
        <div>
          <h1 class="text-lg font-bold text-white tracking-tight">Albayan Study Monitor</h1>
          <p class="text-xs text-slate-400">Lab Parental Control & Screen Review</p>
        </div>
      </div>

      <div class="flex items-center gap-4">
        <div class="hidden sm:flex items-center gap-2 bg-slate-800/60 px-3 py-1.5 rounded-lg border border-slate-700/50 text-xs">
          <span class="text-slate-400">Server:</span>
          <span id="serverIpPill" class="text-indigo-400 font-mono font-semibold">192.168.1.3:8899</span>
        </div>

        <button onclick="logout()" class="text-xs text-slate-400 hover:text-white bg-slate-800/50 hover:bg-slate-800 px-3 py-1.5 rounded-lg border border-slate-700/50 transition">
          <i class="fa-solid fa-arrow-right-from-bracket mr-1"></i> Logout
        </button>
      </div>
    </div>
  </header>

  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <!-- ⚡ WEB DOWNLOAD & INSTALL BANNER -->
    <div class="bg-gradient-to-r from-indigo-950/80 via-slate-900 to-indigo-950/80 border border-indigo-500/40 rounded-2xl p-6 mb-8 flex flex-col md:flex-row items-center justify-between gap-6 shadow-2xl">
      <div class="flex items-center gap-4">
        <div class="w-14 h-14 bg-gradient-to-tr from-indigo-600 to-cyan-500 rounded-2xl flex items-center justify-center text-white text-2xl shadow-lg shadow-indigo-600/30 shrink-0">
          <i class="fa-solid fa-cloud-arrow-down"></i>
        </div>
        <div>
          <div class="flex items-center gap-2">
            <h3 class="text-lg font-bold text-white tracking-tight">Install Software on this PC</h3>
            <span class="bg-indigo-500/20 text-indigo-300 text-[11px] font-mono px-2 py-0.5 rounded border border-indigo-500/30">1-Click Setup</span>
          </div>
          <p class="text-xs text-slate-300 mt-1 max-w-xl">
            ലാബിലെ മറ്റേതെങ്കിലും കമ്പ്യൂട്ടറിൽ (PC 2, PC 3, PC 4) വെബ്സൈറ്റ് തുറന്ന ശേഷം താഴെയുള്ള ബട്ടൺ ക്ലിക്ക് ചെയ്താൽ സോഫ്റ്റ്‌വെയർ ഉടൻ ഇൻസ്റ്റാൾ ആകും!
          </p>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-3 shrink-0">
        <a href="/api/download/setup-script" download="albayan_setup.bat" class="px-5 py-3 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-bold shadow-lg shadow-indigo-600/30 transition flex items-center gap-2">
          <i class="fa-solid fa-bolt text-amber-300"></i> Download 1-Click Installer (.bat)
        </a>
        <a href="/api/download/client-zip" download="albayan_monitor_full.zip" class="px-4 py-3 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-semibold border border-slate-700 transition flex items-center gap-2">
          <i class="fa-solid fa-file-zipper"></i> Full Zip Package
        </a>
      </div>
    </div>

    <!-- Lab Computers Status Cards (albayan 1, 2, 3, 4) - NO DUPLICATES -->
    <div class="mb-8">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm uppercase font-semibold text-slate-400 tracking-wider">
          <i class="fa-solid fa-desktop mr-2 text-indigo-400"></i>Albayan Computers (4 PCs)
        </h3>
        <span id="onlineCounter" class="text-xs font-semibold text-emerald-400 bg-emerald-500/10 px-2.5 py-1 rounded-full border border-emerald-500/20">
          0 Online
        </span>
      </div>

      <div id="computersBar" class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <!-- Rendered dynamically -->
      </div>
    </div>

    <!-- Quick Stats -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
      <div class="bg-slate-900/70 border border-slate-800/80 rounded-2xl p-5">
        <div class="flex items-center justify-between">
          <span class="text-xs uppercase font-semibold text-slate-400">Recordings (Last 24h)</span>
          <i class="fa-solid fa-film text-cyan-400 text-lg"></i>
        </div>
        <p id="statTotalClips" class="text-2xl font-bold text-white mt-2">0</p>
        <p class="text-xs text-slate-500 mt-1" id="statTotalSize">0 MB stored (2-min clips)</p>
      </div>

      <div class="bg-slate-900/70 border border-slate-800/80 rounded-2xl p-5">
        <div class="flex items-center justify-between">
          <span class="text-xs uppercase font-semibold text-slate-400">Auto-Delete Policy</span>
          <i class="fa-solid fa-trash-clock text-amber-400 text-lg"></i>
        </div>
        <p class="text-2xl font-bold text-amber-300 mt-2">24 Hours</p>
        <p class="text-xs text-slate-500 mt-1">Older files automatically wiped</p>
      </div>

      <div class="bg-slate-900/70 border border-slate-800/80 rounded-2xl p-5">
        <div class="flex items-center justify-between">
          <span class="text-xs uppercase font-semibold text-slate-400">Telegram Bot</span>
          <i class="fa-brands fa-telegram text-sky-400 text-lg"></i>
        </div>
        <div class="flex items-center justify-between mt-2">
          <p id="statTelegram" class="text-lg font-bold text-sky-400">Connected</p>
          <span id="telegramModeBadge" class="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300">
            Videos Hidden
          </span>
        </div>
        <div class="flex items-center justify-between text-xs mt-2">
          <a href="https://t.me/my_library_data_bot" target="_blank" class="text-sky-300 hover:underline">
            @my_library_data_bot <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
          </a>
          <span class="text-slate-500">2-min chunk active</span>
        </div>
      </div>
    </div>

    <!-- Video Player Section (When a video is clicked) -->
    <div id="playerSection" class="hidden mb-8 bg-slate-900 border border-indigo-500/30 rounded-2xl p-5 shadow-2xl">
      <div class="flex items-center justify-between mb-4">
        <div>
          <div class="flex items-center gap-2">
            <span id="currentVideoPc" class="px-2 py-0.5 rounded bg-indigo-600/30 text-indigo-300 text-xs font-mono font-bold">albayan 1</span>
            <h2 id="currentVideoTitle" class="text-lg font-semibold text-white">Video Player</h2>
          </div>
          <p id="currentVideoSub" class="text-xs text-slate-400 mt-0.5">Playing chunk</p>
        </div>
        <button onclick="closePlayer()" class="text-slate-400 hover:text-white px-3 py-1 bg-slate-800 rounded-lg text-xs">
          <i class="fa-solid fa-xmark mr-1"></i> Close
        </button>
      </div>
      <div class="bg-black rounded-xl overflow-hidden aspect-video max-h-[550px] flex items-center justify-center">
        <video id="mainVideoPlayer" controls autoplay class="w-full h-full" preload="auto">
          Your browser does not support HTML5 video.
        </video>
      </div>
      <div class="mt-4 flex flex-wrap items-center justify-between gap-4">
        <div class="flex items-center gap-2">
          <span class="text-xs text-slate-400 font-semibold uppercase">Speed:</span>
          <button onclick="setSpeed(1.0)" class="speed-btn px-2.5 py-1 text-xs rounded bg-slate-800 text-slate-300 hover:bg-slate-700">1.0x</button>
          <button onclick="setSpeed(1.25)" class="speed-btn px-2.5 py-1 text-xs rounded bg-slate-800 text-slate-300 hover:bg-slate-700">1.25x</button>
          <button onclick="setSpeed(1.5)" class="speed-btn px-2.5 py-1 text-xs rounded bg-slate-800 text-slate-300 hover:bg-slate-700">1.5x</button>
          <button onclick="setSpeed(2.0)" class="speed-btn px-2.5 py-1 text-xs rounded bg-slate-800 text-slate-300 hover:bg-slate-700">2.0x</button>
        </div>
        <div class="flex items-center gap-3">
          <a id="downloadBtn" href="#" download class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-medium">
            <i class="fa-solid fa-download mr-1"></i> Download Clip
          </a>
        </div>
      </div>
    </div>

    <!-- Recordings List with Filter -->
    <div class="bg-slate-900/70 border border-slate-800/80 rounded-2xl p-6">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <h2 class="text-lg font-bold text-white tracking-tight">Screen Recordings (Last 24 Hours)</h2>
          <p class="text-xs text-slate-400 mt-1">Recorded at 10 FPS in 2-minute clips. Plays smoothly in browser.</p>
        </div>
        
        <div class="flex items-center gap-3">
          <label class="text-xs text-slate-400 font-semibold uppercase">Filter PC:</label>
          <select id="pcFilterSelect" onchange="loadRecordings()" class="bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-1.5 text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none">
            <option value="all">All Computers</option>
            <option value="albayan 1">albayan 1</option>
            <option value="albayan 2">albayan 2</option>
            <option value="albayan 3">albayan 3</option>
            <option value="albayan 4">albayan 4</option>
          </select>

          <button onclick="loadRecordings()" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium transition flex items-center gap-1.5">
            <i class="fa-solid fa-rotate-right"></i> Refresh
          </button>
        </div>
      </div>

      <div id="videoGrid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"></div>

      <div id="emptyState" class="hidden py-16 text-center">
        <div class="w-16 h-16 bg-slate-800/50 rounded-2xl mx-auto flex items-center justify-center text-slate-500 text-2xl mb-3">
          <i class="fa-solid fa-video-slash"></i>
        </div>
        <h3 class="text-base font-semibold text-slate-300">No Recordings Found</h3>
        <p class="text-xs text-slate-500 max-w-sm mx-auto mt-1">
          Each computer uploads a 2-minute video clip as soon as it completes. Please wait a moment if the PC just started!
        </p>
      </div>
    </div>
  </main>

  <script>
    async function updateStatus() {
      try {
        const res = await fetch('/api/status');
        if (res.status === 401) { window.location.reload(); return; }
        const data = await res.json();
        
        document.getElementById('serverIpPill').innerText = `${data.server_ip}:${data.server_port}`;

        const compBar = document.getElementById('computersBar');
        compBar.innerHTML = '';
        
        const computers = data.computers || [];
        computers.forEach(c => {
          const card = document.createElement('div');
          card.className = `p-3.5 rounded-xl border flex items-center justify-between ${
            c.is_online 
              ? 'bg-emerald-500/5 border-emerald-500/30' 
              : 'bg-slate-900/40 border-slate-800'
          }`;
          card.innerHTML = `
            <div>
              <div class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full ${c.is_online ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}"></span>
                <span class="text-sm font-bold text-white">${c.name}</span>
              </div>
              <p class="text-[11px] text-slate-400 mt-1 font-mono">${c.ip}</p>
            </div>
            <span class="text-[11px] font-semibold ${c.is_online ? 'text-emerald-400' : 'text-slate-500'}">
              ${c.is_online ? 'REC 10 FPS' : 'Offline'}
            </span>
          `;
          compBar.appendChild(card);
        });

        document.getElementById('onlineCounter').innerText = `${data.total_online} Online`;
        document.getElementById('statTotalClips').innerText = data.total_recordings;
        document.getElementById('statTotalSize').innerText = `${data.total_size_mb} MB stored`;
        document.getElementById('statTelegram').innerText = data.telegram_connected ? 'Connected ✅' : 'Waiting for /start';
        
        const modeBadge = document.getElementById('telegramModeBadge');
        if (data.telegram_videos_enabled) {
          modeBadge.innerText = 'Videos Sent 📹';
          modeBadge.className = 'text-[11px] font-mono px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30';
        } else {
          modeBadge.innerText = 'Videos Hidden 🔇';
          modeBadge.className = 'text-[11px] font-mono px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20';
        }

      } catch (e) {
        console.error(e);
      }
    }

    async function loadRecordings() {
      try {
        const filterVal = document.getElementById('pcFilterSelect').value;
        const url = filterVal && filterVal !== 'all' 
          ? `/api/recordings?computer=${encodeURIComponent(filterVal)}`
          : '/api/recordings';

        const res = await fetch(url);
        if (res.status === 401) { window.location.reload(); return; }
        const data = await res.json();
        
        const grid = document.getElementById('videoGrid');
        const empty = document.getElementById('emptyState');

        grid.innerHTML = '';
        if (!data.recordings || data.recordings.length === 0) {
          empty.classList.remove('hidden');
          return;
        }
        empty.classList.add('hidden');

        data.recordings.forEach(rec => {
          const card = document.createElement('div');
          card.className = 'bg-slate-950/60 border border-slate-800 hover:border-indigo-500/40 rounded-xl p-4 transition-all duration-200 group flex flex-col justify-between';
          card.innerHTML = `
            <div>
              <div class="relative bg-slate-900 rounded-lg aspect-video flex items-center justify-center overflow-hidden mb-3 group-hover:bg-slate-800 transition">
                <i class="fa-solid fa-play text-2xl text-indigo-400 group-hover:scale-110 transition"></i>
                <button onclick="playVideo('${rec.filename}', '${rec.computer}', '${rec.created_at}')" class="absolute inset-0 w-full h-full focus:outline-none"></button>
                <span class="absolute top-2 left-2 bg-indigo-600/80 px-2 py-0.5 rounded text-[11px] text-white font-mono font-bold">${rec.computer}</span>
                <span class="absolute bottom-2 right-2 bg-black/70 px-2 py-0.5 rounded text-[11px] text-slate-300 font-mono">2 Min (10 FPS)</span>
              </div>
              <h4 class="text-sm font-semibold text-white tracking-tight truncate">${rec.filename}</h4>
              <p class="text-xs text-slate-400 mt-1"><i class="fa-regular fa-clock mr-1"></i> ${rec.created_at}</p>
            </div>
            
            <div class="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
              <span class="text-slate-400 font-mono">${rec.size_mb} MB</span>
              <span class="text-amber-400 font-mono text-[11px]">Expires in ${rec.hours_remaining}h</span>
              <div class="flex items-center gap-2">
                <button onclick="deleteRecording('${rec.filename}')" class="text-slate-500 hover:text-rose-400 p-1 transition" title="Delete Now">
                  <i class="fa-regular fa-trash-can"></i>
                </button>
              </div>
            </div>
          `;
          grid.appendChild(card);
        });
      } catch (e) {
        console.error(e);
      }
    }

    function playVideo(filename, computer, timestamp) {
      const section = document.getElementById('playerSection');
      const player = document.getElementById('mainVideoPlayer');
      const title = document.getElementById('currentVideoTitle');
      const sub = document.getElementById('currentVideoSub');
      const pcBadge = document.getElementById('currentVideoPc');
      const dl = document.getElementById('downloadBtn');

      pcBadge.innerText = computer;
      title.innerText = filename;
      sub.innerText = `Recorded from ${computer} at ${timestamp}`;
      player.src = `/api/video/${filename}`;
      dl.href = `/api/video/${filename}`;
      section.classList.remove('hidden');
      player.load();
      player.play().catch(e => console.log('Autoplay handled'));
      section.scrollIntoView({ behavior: 'smooth' });
    }

    function closePlayer() {
      const player = document.getElementById('mainVideoPlayer');
      player.pause();
      document.getElementById('playerSection').classList.add('hidden');
    }

    function setSpeed(speed) {
      const player = document.getElementById('mainVideoPlayer');
      player.playbackRate = speed;
      document.querySelectorAll('.speed-btn').forEach(btn => {
        if (parseFloat(btn.innerText) === speed) {
          btn.className = 'speed-btn px-2.5 py-1 text-xs rounded bg-indigo-600 text-white font-bold';
        } else {
          btn.className = 'speed-btn px-2.5 py-1 text-xs rounded bg-slate-800 text-slate-300 hover:bg-slate-700';
        }
      });
    }

    async function deleteRecording(filename) {
      if (!confirm(`Are you sure you want to delete ${filename}?`)) return;
      try {
        const res = await fetch(`/api/recordings/${filename}`, { method: 'DELETE' });
        if (res.ok) {
          loadRecordings();
          updateStatus();
        }
      } catch (e) {
        alert('Failed to delete file');
      }
    }

    async function logout() {
      await fetch('/api/logout', { method: 'POST' });
      window.location.reload();
    }

    updateStatus();
    loadRecordings();
    setInterval(updateStatus, 5000);
    setInterval(loadRecordings, 10000);
  </script>
</body>
</html>"""

if __name__ == "__main__":
    cfg = load_config()
    host = cfg.get("server_host", "0.0.0.0")
    port = cfg.get("server_port", 8899)
    lan_ip = get_lan_ip()
    print("=" * 60)
    print("  ALBAYAN LAB STUDY MONITOR - 4 COMPUTERS SERVER")
    print("=" * 60)
    print(f" Web Dashboard:     http://localhost:{port}")
    print(f" Lab Network (LAN): http://{lan_ip}:{port}")
    print(" Master Password:   albayan@2026")
    print(" Video Chunks:      2 Minutes (10 FPS with faststart)")
    print("=" * 60)
    uvicorn.run(app, host=host, port=port)
