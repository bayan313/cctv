import os
import json
import time
import secrets
from typing import Optional

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import requests
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import APIKeyCookie

app = FastAPI(title="Albayan Study Monitor - Vercel Cloud Portal")

cookie_scheme = APIKeyCookie(name="session_token", auto_error=False)
active_sessions = set()

# Configuration
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "albayan@2026")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9287027030:AAFeB2BZyF9G87R6ulycSzFFY9yIuqepIFQ")
API_SECRET = os.getenv("API_SECRET", "secure_study_monitor_secret_key_8899")

def verify_session(session_token: Optional[str] = Depends(cookie_scheme)):
    if not session_token or session_token not in active_sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return session_token

def get_telegram_updates():
    if not TELEGRAM_BOT_TOKEN:
        return []
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        res = requests.get(url, params={"limit": 25}, timeout=5)
        if res.status_code == 200:
            return res.json().get("result", [])
    except Exception:
        pass
    return []

# ----------------- ROUTES -----------------

@app.get("/", response_class=HTMLResponse)
def index_page(request: Request, session_token: Optional[str] = Depends(cookie_scheme)):
    if not session_token or session_token not in active_sessions:
        return get_login_html()
    return get_dashboard_html()

@app.post("/api/login")
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
def logout(response: Response, session_token: Optional[str] = Depends(cookie_scheme)):
    if session_token in active_sessions:
        active_sessions.remove(session_token)
    response.delete_cookie("session_token")
    return {"ok": True}

@app.get("/api/status")
def get_status(session: str = Depends(verify_session)):
    updates = get_telegram_updates()
    recent_events = []
    for u in updates[-15:]:
        msg = u.get("message", {})
        text = msg.get("text") or (msg.get("caption") if msg.get("video") else "")
        date_ts = msg.get("date", 0)
        if text:
            recent_events.append({"text": text, "time": date_ts})

    return {
        "portal": "Vercel Cloud",
        "computers": [
            {"name": "albayan 1", "is_online": True, "ip": "Lab LAN"},
            {"name": "albayan 2", "is_online": True, "ip": "Lab LAN"},
            {"name": "albayan 3", "is_online": True, "ip": "Lab LAN"},
            {"name": "albayan 4", "is_online": True, "ip": "Lab LAN"},
        ],
        "total_online": 4,
        "telegram_connected": bool(TELEGRAM_BOT_TOKEN),
        "recent_events": recent_events
    }

@app.get("/api/recordings")
def get_recordings(session: str = Depends(verify_session)):
    updates = get_telegram_updates()
    recordings = []
    
    for u in reversed(updates):
        msg = u.get("message", {})
        video = msg.get("video")
        caption = msg.get("caption", "")
        if video:
            pc_name = "albayan 1"
            if "[" in caption and "]" in caption:
                pc_name = caption[caption.find("[")+1 : caption.find("]")]
            
            file_id = video.get("file_id")
            size_mb = round(video.get("file_size", 0) / (1024 * 1024), 2)
            
            recordings.append({
                "filename": f"[{pc_name}]_recording.mp4",
                "computer": pc_name,
                "created_at": time.strftime("%Y-%m-%d %I:%M %p", time.localtime(msg.get("date", time.time()))),
                "size_mb": size_mb,
                "file_id": file_id
            })

    return {"recordings": recordings, "all_computers": ["albayan 1", "albayan 2", "albayan 3", "albayan 4"]}

# ----------------- HTML TEMPLATES -----------------

def get_login_html():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Albayan Study Monitor - Cloud Portal</title>
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
      <p class="text-sm text-slate-400 mt-1">Vercel Cloud Portal (albayan 1, 2, 3, 4)</p>
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
        <span>Unlock Cloud Portal</span>
        <i class="fa-solid fa-arrow-right"></i>
      </button>
    </form>
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
  <title>Albayan Study Monitor - Cloud Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
  <header class="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md sticky top-0 z-30">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 bg-indigo-600 rounded-xl flex items-center justify-center text-white text-lg shadow-md shadow-indigo-600/30">
          <i class="fa-solid fa-cloud"></i>
        </div>
        <div>
          <h1 class="text-lg font-bold text-white tracking-tight">Albayan Study Monitor</h1>
          <p class="text-xs text-indigo-400">Vercel Cloud Live</p>
        </div>
      </div>

      <div class="flex items-center gap-4">
        <a href="https://t.me/my_library_data_bot" target="_blank" class="text-xs bg-sky-500/10 hover:bg-sky-500/20 text-sky-400 px-3 py-1.5 rounded-lg border border-sky-500/20 flex items-center gap-1.5 transition">
          <i class="fa-brands fa-telegram"></i> @my_library_data_bot
        </a>
        <button onclick="logout()" class="text-xs text-slate-400 hover:text-white bg-slate-800/50 hover:bg-slate-800 px-3 py-1.5 rounded-lg border border-slate-700/50 transition">
          <i class="fa-solid fa-arrow-right-from-bracket mr-1"></i> Logout
        </button>
      </div>
    </div>
  </header>

  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div class="mb-8">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm uppercase font-semibold text-slate-400 tracking-wider">
          <i class="fa-solid fa-desktop mr-2 text-indigo-400"></i>Albayan Computers (4 PCs)
        </h3>
        <span class="text-xs font-semibold text-emerald-400 bg-emerald-500/10 px-2.5 py-1 rounded-full border border-emerald-500/20">
          Auto-Sync Active
        </span>
      </div>

      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div class="p-3.5 rounded-xl border bg-emerald-500/5 border-emerald-500/30 flex items-center justify-between">
          <div>
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <span class="text-sm font-bold text-white">albayan 1</span>
            </div>
            <p class="text-[11px] text-slate-400 mt-1 font-mono">Computer 1</p>
          </div>
          <span class="text-[11px] font-semibold text-emerald-400">10 FPS</span>
        </div>

        <div class="p-3.5 rounded-xl border bg-emerald-500/5 border-emerald-500/30 flex items-center justify-between">
          <div>
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <span class="text-sm font-bold text-white">albayan 2</span>
            </div>
            <p class="text-[11px] text-slate-400 mt-1 font-mono">Computer 2</p>
          </div>
          <span class="text-[11px] font-semibold text-emerald-400">10 FPS</span>
        </div>

        <div class="p-3.5 rounded-xl border bg-emerald-500/5 border-emerald-500/30 flex items-center justify-between">
          <div>
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <span class="text-sm font-bold text-white">albayan 3</span>
            </div>
            <p class="text-[11px] text-slate-400 mt-1 font-mono">Computer 3</p>
          </div>
          <span class="text-[11px] font-semibold text-emerald-400">10 FPS</span>
        </div>

        <div class="p-3.5 rounded-xl border bg-emerald-500/5 border-emerald-500/30 flex items-center justify-between">
          <div>
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <span class="text-sm font-bold text-white">albayan 4</span>
            </div>
            <p class="text-[11px] text-slate-400 mt-1 font-mono">Computer 4</p>
          </div>
          <span class="text-[11px] font-semibold text-emerald-400">10 FPS</span>
        </div>
      </div>
    </div>

    <!-- Info Banner for Vercel -->
    <div class="bg-indigo-950/40 border border-indigo-500/30 rounded-2xl p-6 mb-8">
      <div class="flex items-start gap-4">
        <div class="w-10 h-10 rounded-xl bg-indigo-600/30 flex items-center justify-center text-indigo-400 text-xl shrink-0">
          <i class="fa-solid fa-cloud-arrow-up"></i>
        </div>
        <div>
          <h3 class="text-base font-bold text-white">Vercel Cloud Portal Active</h3>
          <p class="text-xs text-slate-300 mt-1 leading-relaxed">
            Connected to <strong>@my_library_data_bot</strong> and Albayan Lab Network.
            Password: <strong>albayan@2026</strong>. Auto-updates sync continuously from GitHub.
          </p>
        </div>
      </div>
    </div>

    <!-- Recent Activity Log -->
    <div class="bg-slate-900/70 border border-slate-800/80 rounded-2xl p-6">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-base font-bold text-white">Recent Lab Activity</h3>
        <button onclick="loadStatus()" class="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs">
          <i class="fa-solid fa-rotate-right mr-1"></i> Refresh
        </button>
      </div>
      <div id="activityLog" class="space-y-2 text-xs">
        <p class="text-slate-400">Loading updates...</p>
      </div>
    </div>
  </main>

  <script>
    async function loadStatus() {
      try {
        const res = await fetch('/api/status');
        if (res.status === 401) { window.location.reload(); return; }
        const data = await res.json();
        const log = document.getElementById('activityLog');
        
        const events = data.recent_events || [];
        if (events.length === 0) {
          log.innerHTML = '<p class="text-slate-500">No events logged yet. Connect with Telegram.</p>';
          return;
        }

        log.innerHTML = '';
        events.forEach(e => {
          const div = document.createElement('div');
          div.className = 'p-2.5 bg-slate-950/50 border border-slate-800/70 rounded-lg flex items-center justify-between';
          div.innerHTML = `
            <span class="text-slate-200 font-mono">${e.text}</span>
            <span class="text-slate-500 text-[10px]">${new Date(e.time * 1000).toLocaleTimeString()}</span>
          `;
          log.appendChild(div);
        });
      } catch (e) {
        console.error(e);
      }
    }

    async function logout() {
      await fetch('/api/logout', { method: 'POST' });
      window.location.reload();
    }

    loadStatus();
    setInterval(loadStatus, 10000);
  </script>
</body>
</html>"""
