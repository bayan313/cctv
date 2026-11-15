# -*- coding: utf-8 -*-
import os
import sys
import io
import time
import json
import uuid
import socket
import ctypes
import threading
import queue
import subprocess
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import requests
from PIL import ImageGrab, Image
import mss
import numpy as np
import imageio

# Directories
if getattr(sys, 'frozen', False):
    CLIENT_DIR = Path(sys.executable).resolve().parent
else:
    CLIENT_DIR = Path(__file__).resolve().parent

BASE_DIR = CLIENT_DIR.parent
CONFIG_PATH = CLIENT_DIR / "client_config.json"
GLOBAL_CONFIG_PATH = BASE_DIR / "config.json"
STATE_FILE = CLIENT_DIR / "monitor_state.json"
TEMP_DIR = CLIENT_DIR / "temp_records"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

upload_queue = queue.Queue()

def get_recording_state() -> bool:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                return bool(d.get("recording_active", True))
        except Exception:
            pass
    return True

def set_recording_state(active: bool):
    try:
        data = {
            "recording_active": active,
            "updated_at": time.time(),
            "computer_name": getattr(CONFIG, "get", lambda k, d: "albayan")("computer_name", "albayan") if "CONFIG" in globals() else "albayan"
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[State] Error writing state: {e}")

def generate_cctv_icon(target_path: Path):
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), (15, 23, 42, 255))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([4, 4, 60, 60], radius=14, fill=(16, 185, 129, 255))
        # Camera body
        d.rectangle([14, 22, 42, 42], fill=(255, 255, 255, 255))
        # Camera lens
        d.polygon([(42, 26), (50, 20), (50, 44), (42, 38)], fill=(255, 255, 255, 255))
        # Lens center
        d.ellipse([23, 27, 33, 37], fill=(16, 185, 129, 255))
        img.save(str(target_path), format="ICO")
        return True
    except Exception:
        return False

def get_real_desktop_path() -> Path:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        val, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        expanded = os.path.expandvars(val)
        p = Path(expanded)
        if p.exists():
            return p
    except Exception:
        pass
    for cand in [
        Path(os.environ.get("USERPROFILE", "")) / "Desktop",
        Path(os.environ.get("USERPROFILE", "")) / "OneDrive" / "Desktop",
        Path("D:/Users/AL-BAYAN"),
        Path(os.path.expanduser("~/Desktop"))
    ]:
        if cand.exists():
            return cand
    return Path(os.path.expanduser("~"))

def ensure_desktop_shortcut():
    """Creates a clean Desktop shortcut for Albayan CCTV Monitor if not present."""
    if os.name != "nt":
        return
    try:
        desktop_dir = get_real_desktop_path()
        shortcut_file = desktop_dir / "Albayan CCTV Monitor.lnk"

        ico_file = CLIENT_DIR / "cctv_icon.ico"
        if not ico_file.exists():
            generate_cctv_icon(ico_file)

        icon_loc = str(ico_file) if ico_file.exists() else "shell32.dll,14"

        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        if not Path(pythonw).exists():
            pythonw = sys.executable

        target_script = Path(__file__).resolve()

        ps_cmd = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$sc = $ws.CreateShortcut('{str(shortcut_file)}'); "
            f"$sc.TargetPath = '{pythonw}'; "
            f"$sc.Arguments = '\"{str(target_script)}\" --gui'; "
            f"$sc.WorkingDirectory = '{str(CLIENT_DIR)}'; "
            f"$sc.IconLocation = '{icon_loc}'; "
            f"$sc.Description = 'Albayan CCTV Monitor - Control Panel'; "
            f"$sc.Save()"
        )
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], capture_output=True, timeout=8)
        print(f"[{COMPUTER_NAME}] Desktop shortcut created: {shortcut_file}")
    except Exception as e:
        print(f"[{COMPUTER_NAME}] Error creating desktop shortcut: {e}")

DEFAULT_PC_NAMES = ["albayan 1", "albayan 2", "albayan 3", "albayan 4"]
IDENTITY_FILE = CLIENT_DIR / ".device_identity.json"

def normalize_pc_name(name: str) -> str:
    clean = str(name).strip()
    c_up = clean.upper()
    if c_up in ["PC-01", "PC-1", "PC1", "ALBAYAN 1"]:
        return "albayan 1"
    if c_up in ["PC-02", "PC-2", "PC2", "ALBAYAN 2"]:
        return "albayan 2"
    if c_up in ["PC-03", "PC-3", "PC3", "ALBAYAN 3"]:
        return "albayan 3"
    if c_up in ["PC-04", "PC-4", "PC4", "ALBAYAN 4"]:
        return "albayan 4"
    return clean.lower()

def get_machine_id() -> str:
    """Returns permanent, immutable hardware Machine ID for this physical PC."""
    # 1. Official Windows MachineGuid from Registry (Permanent across all reboots & updates)
    if os.name == "nt":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
            val, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
            if val and len(str(val)) > 8:
                return str(val).strip().lower()
        except Exception:
            pass

        # 2. Try stored AlbayanMonitor MachineId in HKCU
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\AlbayanMonitor", 0, winreg.KEY_READ)
            val, _ = winreg.QueryValueEx(key, "MachineId")
            winreg.CloseKey(key)
            if val and len(str(val)) > 4:
                return str(val).strip().lower()
        except Exception:
            pass

    # 3. Hardware node fallback & persist to registry
    try:
        node = str(uuid.getnode())
        host = socket.gethostname().lower()
        stable_id = f"{host}-{node}"
        if os.name == "nt":
            try:
                import winreg
                k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\AlbayanMonitor")
                winreg.SetValueEx(k, "MachineId", 0, winreg.REG_SZ, stable_id)
                winreg.CloseKey(k)
            except Exception:
                pass
        return stable_id
    except Exception:
        return "device_albayan_unknown"

def get_permanent_pc_name() -> Optional[str]:
    """Retrieves the permanently locked computer name for this PC."""
    # 1. Check Windows Registry (Highest priority, immune to file deletion)
    if os.name == "nt":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\AlbayanMonitor", 0, winreg.KEY_READ)
            val, _ = winreg.QueryValueEx(key, "ComputerName")
            winreg.CloseKey(key)
            if val and str(val).strip():
                return normalize_pc_name(str(val))
        except Exception:
            pass

    # 2. Check local client_config.json
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                c = json.load(f)
                if c.get("computer_name"):
                    return normalize_pc_name(c["computer_name"])
        except Exception:
            pass

    # 3. Check config.json in client dir
    local_cfg = CLIENT_DIR / "config.json"
    if local_cfg.exists():
        try:
            with open(local_cfg, "r", encoding="utf-8") as f:
                c = json.load(f)
                if c.get("computer_name"):
                    return normalize_pc_name(c["computer_name"])
        except Exception:
            pass

    # 4. Check persistent .device_identity.json
    if IDENTITY_FILE.exists():
        try:
            with open(IDENTITY_FILE, "r", encoding="utf-8") as f:
                c = json.load(f)
                if c.get("computer_name"):
                    return normalize_pc_name(c["computer_name"])
        except Exception:
            pass

    return None

def save_permanent_pc_name(name: str):
    """Permanently locks in the computer name across Registry and all config stores."""
    clean = normalize_pc_name(name)
    # 1. Save to Windows Registry
    if os.name == "nt":
        try:
            import winreg
            k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\AlbayanMonitor")
            winreg.SetValueEx(k, "ComputerName", 0, winreg.REG_SZ, clean)
            winreg.CloseKey(k)
        except Exception as e:
            print(f"[Identity] Registry save notice: {e}")

    # 2. Save to client_config.json
    try:
        cur_cfg = {}
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cur_cfg = json.load(f)
        cur_cfg["computer_name"] = clean
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cur_cfg, f, indent=2)
    except Exception:
        pass

    # 3. Save to config.json
    try:
        local_cfg = CLIENT_DIR / "config.json"
        cur_cfg2 = {}
        if local_cfg.exists():
            with open(local_cfg, "r", encoding="utf-8") as f:
                cur_cfg2 = json.load(f)
        cur_cfg2["computer_name"] = clean
        with open(local_cfg, "w", encoding="utf-8") as f:
            json.dump(cur_cfg2, f, indent=2)
    except Exception:
        pass

    # 4. Save to .device_identity.json
    try:
        with open(IDENTITY_FILE, "w", encoding="utf-8") as f:
            json.dump({"computer_name": clean, "device_id": get_machine_id(), "locked_at": time.time()}, f, indent=2)
    except Exception:
        pass

    print(f"🔒 [Identity] Computer Name PERMANENTLY LOCKED as: [{clean}]")

def discover_server_url():
    candidates = []
    # 1. Local server priority (fastest and always reliable on host)
    for local in ["http://127.0.0.1:8899", "http://localhost:8899"]:
        if local not in candidates:
            candidates.append(local)

    # 2. Real Web Cloud Server (Always online 24/7 - zero manual server required)
    for cloud in ["https://cctv-lac-two.vercel.app"]:
        if cloud not in candidates:
            candidates.append(cloud)

    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                c = json.load(f)
                s = c.get("server_url")
                if s and s not in candidates:
                    candidates.append(s)
        except Exception:
            pass

    if GLOBAL_CONFIG_PATH.exists():
        try:
            with open(GLOBAL_CONFIG_PATH, "r", encoding="utf-8") as f:
                g = json.load(f)
                sip = g.get("server_ip")
                sport = g.get("server_port", 8899)
                if sip:
                    url = f"http://{sip}:{sport}"
                    if url not in candidates:
                        candidates.append(url)
                pub = g.get("public_web_url")
                if pub and pub not in candidates:
                    candidates.append(pub)
        except Exception:
            pass

    for fallback in ["http://192.168.1.2:8899", "http://192.168.1.3:8899"]:
        if fallback not in candidates:
            candidates.append(fallback)

    for url in candidates:
        try:
            r = requests.get(f"{url}/api/ping", timeout=2.0)
            if r.status_code == 200:
                return url
        except Exception:
            try:
                r2 = requests.get(f"{url}/api/status", timeout=2.0)
                if r2.status_code in [200, 401]:
                    return url
            except Exception:
                pass

    return "http://127.0.0.1:8899"

def auto_register_pc():
    dev_id = get_machine_id()
    srv_url = discover_server_url()
    existing_name = get_permanent_pc_name()

    try:
        payload = {"device_id": dev_id}
        if existing_name:
            payload["computer_name"] = existing_name

        res = requests.post(
            f"{srv_url}/api/client/register",
            json=payload,
            timeout=5
        )
        if res.status_code == 200:
            data = res.json()
            assigned = existing_name or data.get("computer_name", "albayan 1")
            clean_name = normalize_pc_name(assigned)
            save_permanent_pc_name(clean_name)
            cfg = {
                "computer_name": clean_name,
                "server_url": srv_url,
                "api_secret": data.get("api_secret", "secure_study_monitor_secret_key_8899"),
                "screenshot_interval_seconds": 300,
                "live_stream_interval_seconds": 5
            }
            return cfg
    except Exception as e:
        print(f"[Register] Server connect notice: {e}")

    default_name = existing_name or "albayan 1"
    save_permanent_pc_name(default_name)
    return {
        "computer_name": default_name,
        "server_url": srv_url,
        "api_secret": "secure_study_monitor_secret_key_8899",
        "screenshot_interval_seconds": 300,
        "live_stream_interval_seconds": 5
    }

def load_config():
    permanent_name = get_permanent_pc_name()
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if permanent_name:
                    cfg["computer_name"] = permanent_name
                elif cfg.get("computer_name"):
                    cfg["computer_name"] = normalize_pc_name(cfg["computer_name"])
                    save_permanent_pc_name(cfg["computer_name"])
                if cfg.get("computer_name"):
                    return cfg
        except Exception:
            pass
    return auto_register_pc()

CONFIG = load_config()
COMPUTER_NAME = normalize_pc_name(CONFIG.get("computer_name", "albayan 1"))
SERVER_URL = CONFIG.get("server_url", "http://127.0.0.1:8899").rstrip("/")
API_SECRET = CONFIG.get("api_secret", "secure_study_monitor_secret_key_8899")
SCREENSHOT_INTERVAL = int(CONFIG.get("screenshot_interval_seconds", 300)) # 5 minutes
LIVE_INTERVAL = int(CONFIG.get("live_stream_interval_seconds", 4)) # 4 seconds
VIDEO_RECORDING_ENABLED = bool(CONFIG.get("video_recording_enabled", True))
VIDEO_FPS = int(CONFIG.get("video_fps", 5)) # 5 FPS: Ultra-light, smooth 24h recording
CHUNK_MINUTES = int(CONFIG.get("video_chunk_minutes", 5)) # 5-minute video chunks

# ----------------- 1. RELIABLE NON-BLACK SCREEN CAPTURE -----------------

def ensure_interactive_desktop():
    """Attaches the calling Windows thread to the active interactive input desktop (WinSta0\\default)."""
    try:
        user32 = ctypes.windll.user32
        desk = user32.OpenInputDesktop(0, False, 0x01FF)
        if desk:
            user32.SetThreadDesktop(desk)
            return True
    except Exception:
        pass
    return False

def capture_desktop_image():
    """
    Captures Windows desktop screen reliably.
    Attaches thread to interactive desktop session to ensure NO BLACK SCREEN.
    """
    ensure_interactive_desktop()

    # Method 1: Pillow ImageGrab
    try:
        img = ImageGrab.grab(all_screens=True)
        if img:
            arr = np.array(img)
            if arr.mean() > 1.0:
                return img
    except Exception:
        pass

    # Method 2: mss fallback
    try:
        with mss.MSS() as sct:
            mon = sct.monitors[1]
            shot = sct.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            arr = np.array(img)
            if arr.mean() > 1.0:
                return img
    except Exception:
        pass

    # Method 3: Return last attempt even if dark (e.g. user has black wallpaper)
    try:
        return ImageGrab.grab(all_screens=True)
    except Exception:
        pass

    return None

# ----------------- 2. POPUP NOTIFICATION (OVERT CENTER TYPEWRITER) -----------------

def run_popup_ui():
    """Isolated popup UI function that runs in a standalone child process."""
    import tkinter as tk
    try:
        root = tk.Tk()
        root.title("Screen Recording Active")
        root.attributes("-topmost", True)
        root.overrideredirect(True)

        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        w, h = 560, 160
        x = max(0, (screen_w - w) // 2)
        y = max(0, (screen_h - h) // 2)
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.configure(bg="#020617")

        frame = tk.Frame(root, bg="#0f172a", highlightbackground="#ef4444", highlightthickness=2.5, padx=24, pady=20)
        frame.pack(fill="both", expand=True)

        header_lbl = tk.Label(
            frame,
            text=f"[{COMPUTER_NAME.upper()}] CCTV MONITOR ACTIVE",
            font=("Segoe UI", 9, "bold"),
            fg="#94a3b8",
            bg="#0f172a"
        )
        header_lbl.pack(anchor="center", pady=(0, 4))

        type_lbl = tk.Label(
            frame,
            text="",
            font=("Consolas", 18, "bold"),
            fg="#ef4444",
            bg="#0f172a"
        )
        type_lbl.pack(anchor="center", pady=(0, 6))

        sub_lbl = tk.Label(
            frame,
            text="This computer is under screen monitoring. Recording in progress.",
            font=("Segoe UI", 9),
            fg="#64748b",
            bg="#0f172a"
        )
        sub_lbl.pack(anchor="center")

        full_text = "● SCREEN RECORDING STARTED"
        state = {"idx": 0}

        def type_step():
            if state["idx"] < len(full_text):
                state["idx"] += 1
                type_lbl.config(text=full_text[:state["idx"]])
                root.after(45, type_step)
            else:
                root.after(3000, root.destroy)

        root.after(150, type_step)
        root.mainloop()
    except Exception:
        pass
    sys.exit(0)

def show_recording_popup():
    """
    Displays an overt centered notification when PC powers on / starts up:
    Types out: "● SCREEN RECORDING STARTED" in the exact CENTER of the screen,
    pauses for a few seconds, then automatically closes and continues running in the background.
    Runs in an isolated child subprocess to guarantee 100% thread safety and eliminate Tkinter Tcl crashes.
    """
    try:
        if getattr(sys, 'frozen', False):
            subprocess.run([sys.executable, "--popup"], timeout=15)
        else:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--popup"], timeout=15)
    except Exception as e:
        print(f"[Popup] Isolated popup finished: {e}")

def execute_system_shutdown():
    print(f"[{COMPUTER_NAME}] 🚨 REMOTE SHUTDOWN RECEIVED FROM SERVER! Shutting down immediately...")
    try:
        subprocess.run(["shutdown", "/s", "/f", "/t", "0"], shell=True)
    except Exception:
        pass
    try:
        os.system("shutdown /s /f /t 0")
    except Exception:
        pass

def generate_paused_frame():
    try:
        card = Image.new("RGB", (960, 540), (15, 23, 42))
        d = ImageDraw.Draw(card)
        d.rectangle([20, 20, 940, 520], outline=(239, 68, 68), width=3)
        now_str = datetime.now().strftime("%I:%M:%S %p")
        d.rectangle([20, 20, 940, 80], fill=(30, 41, 59))
        d.text((480, 50), f"[{COMPUTER_NAME.upper()}] - CCTV SCREEN MONITOR", fill=(248, 250, 252), anchor="mm")
        d.text((480, 240), "■ RECORDING PAUSED BY ADMIN", fill=(239, 68, 68), anchor="mm")
        d.text((480, 280), "Screen video recording & live monitoring temporarily suspended", fill=(148, 163, 184), anchor="mm")
        d.text((480, 320), f"Status Check: {now_str}", fill=(100, 116, 139), anchor="mm")
        return card
    except Exception:
        return None

# ----------------- 3. LIVE CCTV STREAMER (EVERY 5 SECONDS) -----------------

def live_cctv_worker():
    """Sends a fast live thumbnail frame every 5 seconds to power the CCTV quad monitor."""
    print(f"[{COMPUTER_NAME}] Live CCTV streamer started (every {LIVE_INTERVAL}s)...")
    while True:
        try:
            if not get_recording_state():
                img = generate_paused_frame()
            else:
                img = capture_desktop_image()
            if img:
                # Resize to 960x540 for lightweight live streaming
                thumb = img.copy()
                thumb.thumbnail((960, 540))
                buf = io.BytesIO()
                thumb.save(buf, format="JPEG", quality=65)
                buf.seek(0)

                files = {"frame": (f"{COMPUTER_NAME}.jpg", buf, "image/jpeg")}
                data = {"computer_name": COMPUTER_NAME}
                headers = {"X-API-Secret": API_SECRET}
                res = requests.post(
                    f"{SERVER_URL}/api/client/live_frame",
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=5
                )
                if res.status_code == 200:
                    try:
                        rdata = res.json()
                        if rdata.get("command") == "shutdown":
                            execute_system_shutdown()
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(LIVE_INTERVAL)

# ----------------- 4. 5-MINUTE SCREENSHOT RECORDER -----------------

def five_minute_screenshot_worker():
    """Captures and uploads a high-resolution screenshot every 5 minutes."""
    print(f"[{COMPUTER_NAME}] 5-minute screenshot scheduler active...")
    while True:
        try:
            if not get_recording_state():
                time.sleep(5)
                continue
            img = capture_desktop_image()
            if img:
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"[{COMPUTER_NAME}]_{timestamp_str}.jpg"
                
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80)
                buf.seek(0)

                files = {"screenshot": (filename, buf, "image/jpeg")}
                data = {
                    "computer_name": COMPUTER_NAME,
                    "timestamp": timestamp_str
                }
                headers = {"X-API-Secret": API_SECRET}

                res = requests.post(
                    f"{SERVER_URL}/api/client/upload_screenshot",
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=15
                )
                if res.status_code == 200:
                    print(f"[{COMPUTER_NAME}] Saved 5-minute screenshot: {filename}")
        except Exception as e:
            print(f"[{COMPUTER_NAME}] Error taking 5-min screenshot: {e}")

        time.sleep(SCREENSHOT_INTERVAL)

# ----------------- 5. PING WORKER -----------------

def ping_worker():
    global LIVE_INTERVAL, SCREENSHOT_INTERVAL, VIDEO_RECORDING_ENABLED, VIDEO_FPS, CHUNK_MINUTES
    while True:
        try:
            res = requests.post(
                f"{SERVER_URL}/api/client/ping",
                headers={"X-API-Secret": API_SECRET},
                json={"computer_name": COMPUTER_NAME},
                timeout=5
            )
            if res.status_code == 200:
                data = res.json()
                if data.get("command") == "shutdown":
                    execute_system_shutdown()
                c = data.get("config")
                if c:
                    if "video_fps" in c and int(c["video_fps"]) > 0:
                        VIDEO_FPS = int(c["video_fps"])
                    if "video_chunk_minutes" in c and int(c["video_chunk_minutes"]) > 0:
                        CHUNK_MINUTES = int(c["video_chunk_minutes"])
                    if "video_recording_enabled" in c:
                        VIDEO_RECORDING_ENABLED = bool(c["video_recording_enabled"])
                    if "live_stream_interval_seconds" in c and int(c["live_stream_interval_seconds"]) > 0:
                        LIVE_INTERVAL = int(c["live_stream_interval_seconds"])
                    if "screenshot_interval_seconds" in c and int(c["screenshot_interval_seconds"]) > 0:
                        SCREENSHOT_INTERVAL = int(c["screenshot_interval_seconds"])
        except Exception:
            pass
        time.sleep(20)

# ----------------- 6. SAFE OVER-THE-AIR AUTO-UPDATER -----------------

def auto_updater_worker():
    """
    Over-The-Air Automatic Self-Updater:
    Checks GitHub and Web Server every 15 minutes.
    If an updated version of recorder.py is found, it silently downloads it,
    validates the syntax, updates its own file on disk, and seamlessly restarts.
    Zero manual interaction required after 1-time setup on any PC!
    """
    if getattr(sys, 'frozen', False):
        return
    time.sleep(30)
    current_script = Path(__file__).resolve()

    while True:
        try:
            # 1. If running inside a git clone, try git pull first
            if (BASE_DIR / ".git").exists():
                try:
                    subprocess.run(["git", "fetch", "origin", "main"], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=20)
                    res = subprocess.run(["git", "status", "-uno"], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=10)
                    if "Your branch is behind" in res.stdout:
                        print(f"[{COMPUTER_NAME}] Safe Auto-Update: Pulling latest features from GitHub...")
                        subprocess.run(["git", "pull", "--no-rebase", "origin", "main"], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=30)
                        print(f"[{COMPUTER_NAME}] Git update applied. Restarting...")
                        python = sys.executable
                        os.execl(python, python, *sys.argv)
                except Exception:
                    pass
                time.sleep(900)
                continue

            # 2. Universal OTA update for client PCs (No git needed)
            candidate_urls = [
                "https://raw.githubusercontent.com/bayan313/cctv/main/client/recorder.py",
                f"{SERVER_URL}/api/download/recorder.py",
                "https://cctv-lac-two.vercel.app/api/download/recorder.py"
            ]
            for url in candidate_urls:
                try:
                    r = requests.get(url, timeout=15)
                    if r.status_code == 200 and len(r.content) > 5000 and b"def video_recorder_worker" in r.content:
                        remote_code = r.text
                        local_code = current_script.read_text(encoding="utf-8")
                        remote_hash = hashlib.sha256(remote_code.encode("utf-8")).hexdigest()
                        local_hash = hashlib.sha256(local_code.encode("utf-8")).hexdigest()

                        if remote_hash != local_hash:
                            compile(remote_code, str(current_script), "exec")
                            print(f"[{COMPUTER_NAME}] 🚀 New update found! Applying OTA update from {url}...")
                            current_script.write_text(remote_code, encoding="utf-8")
                            print(f"[{COMPUTER_NAME}] Update written successfully. Restarting process...")
                            time.sleep(1)
                            python = sys.executable
                            os.execl(python, python, *sys.argv)
                            break
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(900) # Check every 15 minutes

# ----------------- 7. VIDEO RECORDER & UPLOADER -----------------

def upload_worker():
    """Uploads completed MP4 video clips to the server."""
    while True:
        file_path = upload_queue.get()
        if not file_path:
            break

        path_obj = Path(file_path)
        if not path_obj.exists():
            upload_queue.task_done()
            continue

        uploaded = False
        retry_delay = 3
        while not uploaded:
            try:
                srv_url = discover_server_url()
                with open(path_obj, "rb") as f:
                    files = {"video": (path_obj.name, f, "video/mp4")}
                    data = {"computer_name": COMPUTER_NAME}
                    headers = {"X-API-Secret": API_SECRET}
                    res = requests.post(
                        f"{srv_url}/api/client/upload_video",
                        files=files,
                        data=data,
                        headers=headers,
                        timeout=90
                    )
                    if res.status_code == 200:
                        uploaded = True
                        print(f"[{COMPUTER_NAME}] Uploaded video {path_obj.name} to server!")
                        try:
                            path_obj.unlink()
                        except Exception:
                            pass
                    else:
                        time.sleep(retry_delay)
                        retry_delay = min(60, retry_delay * 2)
            except Exception as e:
                time.sleep(retry_delay)
                retry_delay = min(60, retry_delay * 2)

        upload_queue.task_done()

def video_recorder_worker():
    """Records smooth screen video in configurable MP4 clips and uploads them."""
    print(f"[{COMPUTER_NAME}] Screen Video Recorder initialized ({VIDEO_FPS} FPS, {CHUNK_MINUTES}-min clips, 24h ultra-low size)...")

    # Enqueue any pending files from previous session, purging files older than 24h
    now_ts = time.time()
    for prev_file in TEMP_DIR.glob("*.mp4"):
        try:
            if now_ts - prev_file.stat().st_mtime > 86400:
                prev_file.unlink()
            else:
                upload_queue.put(str(prev_file))
        except Exception:
            pass

    ensure_interactive_desktop()
    sct_class = getattr(mss, "MSS", mss.mss)
    sct = None
    try:
        sct = sct_class()
        mon = sct.monitors[1]
        width = (mon["width"] // 16) * 16
        height = (mon["height"] // 16) * 16
        capture_box = {"top": mon["top"], "left": mon["left"], "width": width, "height": height}
    except Exception:
        user32 = ctypes.windll.user32
        sw = user32.GetSystemMetrics(0) or 1600
        sh = user32.GetSystemMetrics(1) or 900
        width = (sw // 16) * 16
        height = (sh // 16) * 16
        capture_box = {"top": 0, "left": 0, "width": width, "height": height}

    fallback_frame = np.zeros((height, width, 3), dtype=np.uint8)

    while True:
        if not VIDEO_RECORDING_ENABLED or not get_recording_state():
            time.sleep(2)
            continue

        ensure_interactive_desktop()
        current_fps = max(1, min(60, VIDEO_FPS))
        current_chunk_min = max(1, CHUNK_MINUTES)
        target_frame_time = 1.0 / current_fps

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_filename = f"[{COMPUTER_NAME}]_{timestamp_str}.mp4"
        current_video_path = TEMP_DIR / video_filename

        try:
            writer = imageio.get_writer(
                str(current_video_path),
                fps=current_fps,
                codec="libx264",
                pixelformat="yuv420p",
                macro_block_size=None,
                output_params=[
                    "-vf", "scale='min(960,iw)':-2",
                    "-crf", "32",
                    "-preset", "veryfast",
                    "-g", "25",
                    "-movflags", "+faststart"
                ]
            )
        except Exception:
            try:
                writer = imageio.get_writer(
                    str(current_video_path),
                    fps=current_fps,
                    codec="libx264",
                    quality=5,
                    pixelformat="yuv420p",
                    macro_block_size=16,
                    output_params=["-movflags", "+faststart"]
                )
            except Exception as err:
                print(f"[{COMPUTER_NAME}] Video writer error: {err}")
                time.sleep(3)
                continue

        chunk_start_time = time.time()
        chunk_end_time = chunk_start_time + (current_chunk_min * 60)
        frame_count = 0
        last_valid_frame = None

        while time.time() < chunk_end_time and VIDEO_RECORDING_ENABLED and get_recording_state():
            loop_start = time.time()
            rgb_frame = None

            # 1. Fast MSS Capture
            if sct is not None:
                try:
                    raw_frame = np.array(sct.grab(capture_box))
                    f = raw_frame[:, :, [2, 1, 0]]
                    if f.mean() > 0.5:
                        rgb_frame = f
                except Exception:
                    ensure_interactive_desktop()
                    try:
                        sct = sct_class()
                    except Exception:
                        pass

            # 2. Robust Pillow ImageGrab fallback (guarantees real screen capture)
            if rgb_frame is None:
                try:
                    img = ImageGrab.grab(all_screens=True)
                    if img:
                        if img.size != (width, height):
                            img = img.resize((width, height))
                        f = np.array(img)
                        if f.mean() > 0.5:
                            rgb_frame = f
                except Exception:
                    pass

            # 3. Hold last valid frame (never write black screen during momentary switch)
            if rgb_frame is None and last_valid_frame is not None:
                rgb_frame = last_valid_frame

            # 4. Fallback if no frame ever succeeded
            if rgb_frame is None:
                rgb_frame = fallback_frame
            else:
                last_valid_frame = rgb_frame

            try:
                writer.append_data(rgb_frame)
                frame_count += 1
            except Exception:
                pass

            elapsed = time.time() - loop_start
            sleep_time = target_frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        try:
            writer.close()
            if frame_count > 0 and current_video_path.exists():
                fsize = current_video_path.stat().st_size
                size_str = f"{round(fsize / 1024, 1)} KB" if fsize < 1024 * 1024 else f"{round(fsize / (1024 * 1024), 2)} MB"
                print(f"[{COMPUTER_NAME}] Finished {current_chunk_min}-min video clip: {video_filename} ({size_str})")
                upload_queue.put(str(current_video_path))
        except Exception as e:
            print(f"[{COMPUTER_NAME}] Error closing video writer: {e}")

def ensure_windows_startup():
    """Ensure client automatically launches on PC boot without user interaction."""
    if os.name != "nt":
        return
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if getattr(sys, 'frozen', False):
            cmd = f'"{sys.executable}"'
        else:
            pythonw = sys.executable.replace("python.exe", "pythonw.exe")
            if not Path(pythonw).exists():
                pythonw = sys.executable
            cmd = f'"{pythonw}" "{Path(__file__).resolve()}"'
        winreg.SetValueEx(key, "AlbayanStudyMonitorClient", 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        print(f"[{COMPUTER_NAME}] Windows Startup registered: {cmd}")

        # Dual redundancy: also place hidden VBScript in user's Startup folder
        try:
            startup_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            if startup_dir.exists():
                vbs_file = startup_dir / "StudyMonitorClient.vbs"
                if getattr(sys, 'frozen', False):
                    vbs_content = f'Set WshShell = CreateObject("WScript.Shell")\nWshShell.Run Chr(34) & "{sys.executable}" & Chr(34), 0, False\n'
                else:
                    vbs_content = f'Set WshShell = CreateObject("WScript.Shell")\nWshShell.Run Chr(34) & "{pythonw}" & Chr(34) & " " & Chr(34) & "{Path(__file__).resolve()}" & Chr(34), 0, False\n'
                vbs_file.write_text(vbs_content, encoding="utf-8")
                print(f"[{COMPUTER_NAME}] Dual-startup VBS placed in: {vbs_file}")
        except Exception:
            pass
    except Exception as e:
        print(f"[{COMPUTER_NAME}] Startup register error: {e}")

def is_daemon_running() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 8897))
        s.close()
        return False
    except Exception:
        return True

def ensure_daemon_running():
    if not is_daemon_running():
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        if not Path(pythonw).exists():
            pythonw = sys.executable
        target_script = Path(__file__).resolve()
        try:
            subprocess.Popen([pythonw, str(target_script), "--daemon"], cwd=str(CLIENT_DIR))
            time.sleep(1)
        except Exception:
            pass

def run_control_gui():
    """
    Opens the interactive Control Panel GUI with Password-Protected Start/Stop options.
    """
    import tkinter as tk
    from tkinter import messagebox
    import webbrowser

    ensure_desktop_shortcut()
    ensure_daemon_running()

    root = tk.Tk()
    root.title(f"Albayan CCTV Monitor - [{COMPUTER_NAME.upper()}]")
    root.configure(bg="#090d16")

    ico_file = CLIENT_DIR / "cctv_icon.ico"
    if not ico_file.exists():
        generate_cctv_icon(ico_file)
    if ico_file.exists():
        try:
            root.iconbitmap(str(ico_file))
        except Exception:
            pass

    w, h = 480, 480
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = max(0, (screen_w - w) // 2)
    y = max(0, (screen_h - h) // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.resizable(False, False)

    # Header
    hdr = tk.Frame(root, bg="#090d16", padx=20, pady=16)
    hdr.pack(fill="x")

    title_lbl = tk.Label(hdr, text="ALBAYAN CCTV MONITOR", font=("Segoe UI", 16, "bold"), fg="#38bdf8", bg="#090d16")
    title_lbl.pack(anchor="w")

    sub_lbl = tk.Label(hdr, text="Laboratory Screen Surveillance & Security Control Panel", font=("Segoe UI", 9), fg="#94a3b8", bg="#090d16")
    sub_lbl.pack(anchor="w", pady=(2, 0))

    # Main Card
    card = tk.Frame(root, bg="#1e293b", highlightbackground="#334155", highlightthickness=1.5, padx=20, pady=14)
    card.pack(fill="x", padx=20, pady=(0, 14))

    def make_info_row(parent, label_text, val_text, val_color="#f8fafc"):
        row = tk.Frame(parent, bg="#1e293b")
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label_text, font=("Segoe UI", 9), fg="#94a3b8", bg="#1e293b").pack(side="left")
        tk.Label(row, text=val_text, font=("Segoe UI", 9, "bold"), fg=val_color, bg="#1e293b").pack(side="right")

    row_name = tk.Frame(card, bg="#1e293b")
    row_name.pack(fill="x", pady=2)
    tk.Label(row_name, text="🖥️ Computer Name:", font=("Segoe UI", 9), fg="#94a3b8", bg="#1e293b").pack(side="left")
    name_lbl = tk.Label(row_name, text=f"{COMPUTER_NAME.upper()} (Locked)", font=("Segoe UI", 9, "bold"), fg="#38bdf8", bg="#1e293b")
    name_lbl.pack(side="right")

    make_info_row(card, "🌐 Web Surveillance:", "Connected (Cloud)", "#10b981")
    make_info_row(card, "📹 Video Retention:", f"24 Hours Continuous ({CHUNK_MINUTES}m clips)", "#f8fafc")

    tk.Frame(card, bg="#334155", height=1).pack(fill="x", pady=10)

    # Status indicator
    status_frame = tk.Frame(card, bg="#0f172a", padx=12, pady=10, highlightbackground="#334155", highlightthickness=1.5)
    status_frame.pack(fill="x")

    status_dot = tk.Label(status_frame, text="●", font=("Segoe UI", 14, "bold"), fg="#10b981", bg="#0f172a")
    status_dot.pack(side="left", padx=(0, 6))

    status_text = tk.Label(status_frame, text="RECORDING & TRANSMITTING ACTIVE", font=("Segoe UI", 10, "bold"), fg="#10b981", bg="#0f172a")
    status_text.pack(side="left")

    def update_status_ui():
        is_active = get_recording_state()
        if is_active:
            status_dot.config(text="●", fg="#10b981")
            status_text.config(text="RECORDING & TRANSMITTING ACTIVE", fg="#10b981")
            status_frame.config(highlightbackground="#10b981")
            btn_stop.config(state="normal", bg="#dc2626")
            btn_start.config(state="disabled", bg="#334155")
        else:
            status_dot.config(text="■", fg="#ef4444")
            status_text.config(text="RECORDING STOPPED / PAUSED", fg="#ef4444")
            status_frame.config(highlightbackground="#ef4444")
            btn_stop.config(state="disabled", bg="#334155")
            btn_start.config(state="normal", bg="#16a34a")

    def poll_state():
        update_status_ui()
        root.after(1000, poll_state)

    def prompt_password(action_name):
        dialog = tk.Toplevel(root)
        dialog.title("Admin Authorization")
        dialog.geometry("380x210")
        dialog.configure(bg="#0f172a")
        dialog.transient(root)
        dialog.grab_set()
        dialog.resizable(False, False)

        dx = x + (w - 380) // 2
        dy = y + (h - 210) // 2
        dialog.geometry(f"+{dx}+{dy}")

        lbl = tk.Label(
            dialog,
            text=f"🔒 Enter Admin Password to {action_name}:",
            font=("Segoe UI", 10, "bold"),
            fg="#f8fafc",
            bg="#0f172a",
            wraplength=340
        )
        lbl.pack(pady=(18, 10))

        pwd_var = tk.StringVar()
        entry = tk.Entry(
            dialog,
            textvariable=pwd_var,
            show="*",
            font=("Segoe UI", 12),
            bg="#1e293b",
            fg="#f8fafc",
            insertbackground="#f8fafc",
            justify="center",
            relief="solid",
            highlightthickness=1,
            highlightbackground="#475569"
        )
        entry.pack(pady=6, padx=30, fill="x")
        entry.focus_set()

        err_lbl = tk.Label(dialog, text="", font=("Segoe UI", 8), fg="#ef4444", bg="#0f172a")
        err_lbl.pack(pady=(2, 6))

        result = {"success": False}

        def on_confirm(event=None):
            entered = pwd_var.get().strip()
            valid_pwds = ["974621467097458841599745404128", "albayan@2026"]
            if entered in valid_pwds:
                result["success"] = True
                dialog.destroy()
            else:
                err_lbl.config(text="❌ Invalid password! Access Denied.")
                entry.delete(0, tk.END)

        btn_row = tk.Frame(dialog, bg="#0f172a")
        btn_row.pack(pady=4)

        tk.Button(
            btn_row,
            text="Confirm",
            command=on_confirm,
            font=("Segoe UI", 9, "bold"),
            bg="#10b981",
            fg="#ffffff",
            padx=16,
            pady=4,
            relief="flat",
            cursor="hand2"
        ).pack(side="left", padx=6)

        tk.Button(
            btn_row,
            text="Cancel",
            command=dialog.destroy,
            font=("Segoe UI", 9),
            bg="#334155",
            fg="#cbd5e1",
            padx=14,
            pady=4,
            relief="flat",
            cursor="hand2"
        ).pack(side="left", padx=6)

        entry.bind("<Return>", on_confirm)
        dialog.wait_window()
        return result["success"]

    def do_stop():
        if prompt_password("STOP recording"):
            set_recording_state(False)
            update_status_ui()
            messagebox.showinfo("CCTV Control", "⏹ Recording and live stream have been PAUSED.\n\nStatus: STOPPED")

    def do_start():
        if prompt_password("START recording"):
            set_recording_state(True)
            update_status_ui()
            messagebox.showinfo("CCTV Control", "▶ Recording and live stream have been RESUMED.\n\nStatus: ACTIVE")

    def do_rename():
        if prompt_password("LOCK / RENAME Camera"):
            rndlg = tk.Toplevel(root)
            rndlg.title("Permanent Camera Name")
            rndlg.geometry("400x260")
            rndlg.configure(bg="#0f172a")
            rndlg.transient(root)
            rndlg.grab_set()
            rndlg.resizable(False, False)

            dx = x + (w - 400) // 2
            dy = y + (h - 260) // 2
            rndlg.geometry(f"+{dx}+{dy}")

            tk.Label(
                rndlg,
                text="🔒 Select Permanent Camera Slot:",
                font=("Segoe UI", 10, "bold"),
                fg="#f8fafc",
                bg="#0f172a"
            ).pack(pady=(16, 8))

            choice_var = tk.StringVar(value=COMPUTER_NAME)

            btn_grid = tk.Frame(rndlg, bg="#0f172a")
            btn_grid.pack(pady=4)

            for opt in ["albayan 1", "albayan 2", "albayan 3", "albayan 4"]:
                tk.Radiobutton(
                    btn_grid,
                    text=opt.upper(),
                    variable=choice_var,
                    value=opt,
                    font=("Segoe UI", 9, "bold"),
                    fg="#38bdf8",
                    bg="#0f172a",
                    selectcolor="#1e293b",
                    activebackground="#0f172a",
                    activeforeground="#38bdf8"
                ).pack(side="left", padx=4)

            tk.Label(
                rndlg,
                text="Or type custom computer name:",
                font=("Segoe UI", 8),
                fg="#94a3b8",
                bg="#0f172a"
            ).pack(pady=(6, 2))

            custom_entry = tk.Entry(
                rndlg,
                textvariable=choice_var,
                font=("Segoe UI", 11),
                bg="#1e293b",
                fg="#f8fafc",
                justify="center",
                relief="solid",
                highlightthickness=1,
                highlightbackground="#475569"
            )
            custom_entry.pack(pady=4, padx=30, fill="x")

            def on_save_rename():
                new_val = choice_var.get().strip()
                if new_val:
                    clean = normalize_pc_name(new_val)
                    save_permanent_pc_name(clean)
                    global COMPUTER_NAME
                    COMPUTER_NAME = clean
                    name_lbl.config(text=f"{clean.upper()} (Locked)")
                    root.title(f"Albayan CCTV Monitor - [{clean.upper()}]")
                    try:
                        requests.post(
                            f"{SERVER_URL}/api/client/register",
                            json={"device_id": get_machine_id(), "computer_name": clean},
                            timeout=5
                        )
                    except Exception:
                        pass
                    rndlg.destroy()
                    messagebox.showinfo("CCTV Control", f"✅ Camera Name successfully LOCKED as:\n\n[{clean.upper()}]\n\nThis name will remain permanently fixed across all reboots!")

            btn_r = tk.Frame(rndlg, bg="#0f172a")
            btn_r.pack(pady=10)

            tk.Button(btn_r, text="Lock & Save Name", command=on_save_rename, font=("Segoe UI", 9, "bold"), bg="#10b981", fg="#ffffff", padx=16, pady=4, relief="flat", cursor="hand2").pack(side="left", padx=6)
            tk.Button(btn_r, text="Cancel", command=rndlg.destroy, font=("Segoe UI", 9), bg="#334155", fg="#cbd5e1", padx=14, pady=4, relief="flat", cursor="hand2").pack(side="left", padx=6)

    def do_open_web():
        webbrowser.open(SERVER_URL if "vercel" in SERVER_URL else "https://cctv-lac-two.vercel.app")

    def do_close():
        root.destroy()

    btn_frame = tk.Frame(root, bg="#090d16", padx=20)
    btn_frame.pack(fill="x", pady=4)

    btn_stop = tk.Button(
        btn_frame,
        text="⏹  STOP RECORDING (Password Required)",
        font=("Segoe UI", 10, "bold"),
        bg="#dc2626",
        fg="#ffffff",
        activebackground="#b91c1c",
        activeforeground="#ffffff",
        pady=7,
        relief="flat",
        cursor="hand2",
        command=do_stop
    )
    btn_stop.pack(fill="x", pady=3)

    btn_start = tk.Button(
        btn_frame,
        text="▶  START RECORDING (Password Required)",
        font=("Segoe UI", 10, "bold"),
        bg="#16a34a",
        fg="#ffffff",
        activebackground="#15803d",
        activeforeground="#ffffff",
        pady=7,
        relief="flat",
        cursor="hand2",
        command=do_start
    )
    btn_start.pack(fill="x", pady=3)

    btn_rename = tk.Button(
        btn_frame,
        text="✏️  LOCK / RENAME CAMERA (Password Required)",
        font=("Segoe UI", 9, "bold"),
        bg="#1e293b",
        fg="#38bdf8",
        activebackground="#334155",
        activeforeground="#38bdf8",
        pady=5,
        relief="flat",
        cursor="hand2",
        command=do_rename
    )
    btn_rename.pack(fill="x", pady=3)

    btn_web = tk.Button(
        btn_frame,
        text="🌐  VIEW CCTV WEB PORTAL",
        font=("Segoe UI", 9),
        bg="#0f172a",
        fg="#94a3b8",
        activebackground="#1e293b",
        activeforeground="#cbd5e1",
        pady=5,
        relief="flat",
        cursor="hand2",
        command=do_open_web
    )
    btn_web.pack(fill="x", pady=3)

    btn_min = tk.Button(
        btn_frame,
        text="🔽  Minimize to Background (Keep Recording)",
        font=("Segoe UI", 8),
        bg="#090d16",
        fg="#64748b",
        activebackground="#090d16",
        activeforeground="#94a3b8",
        pady=4,
        relief="flat",
        cursor="hand2",
        command=do_close
    )
    btn_min.pack(fill="x", pady=(6, 0))

    root.protocol("WM_DELETE_WINDOW", do_close)
    update_status_ui()
    root.after(1000, poll_state)
    root.mainloop()

# ----------------- MAIN FLOW -----------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--popup":
        run_popup_ui()
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] in ["--gui", "--control"]:
        run_control_gui()
        sys.exit(0)

    # Check if daemon is already running
    daemon_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        daemon_socket.bind(("127.0.0.1", 8897))
    except Exception:
        # Another background daemon is already running; open Control Panel GUI!
        run_control_gui()
        sys.exit(0)

    print(f"=================================================")
    print(f"  ALBAYAN CCTV MONITOR CLIENT - [{COMPUTER_NAME}]")
    print(f"  Mode: Automatic Video Recording + CCTV Feed")
    print(f"  Video Clips: Every {CHUNK_MINUTES} Minutes ({VIDEO_FPS} FPS)")
    print(f"  Live Stream: CCTV Quad Grid (every {LIVE_INTERVAL}s)")
    print(f"=================================================")
    print(f"Initializing (2s startup delay)...")
    time.sleep(2)

    # Automatically ensure Windows Auto-Startup on first run
    ensure_windows_startup()

    # Ensure Desktop Shortcut is created on the user's desktop
    ensure_desktop_shortcut()

    # Show warning popup
    if "--daemon" not in sys.argv and "--silent" not in sys.argv:
        show_recording_popup()

    # Send Boot Notification to Telegram & Server
    try:
        srv = discover_server_url()
        requests.post(
            f"{srv}/api/client/boot_notify",
            headers={"X-API-Secret": API_SECRET},
            json={"computer_name": COMPUTER_NAME},
            timeout=5
        )
    except Exception:
        pass

    # Thread 1: Live CCTV frame stream (every 5 seconds)
    t_live = threading.Thread(target=live_cctv_worker, daemon=True)
    t_live.start()

    # Thread 2: Ping heartbeat (every 20 seconds)
    t_ping = threading.Thread(target=ping_worker, daemon=True)
    t_ping.start()

    # Thread 3: Safe GitHub Auto-Updater
    t_updater = threading.Thread(target=auto_updater_worker, daemon=True)
    t_updater.start()

    # Thread 4: Background Video Uploader
    t_uploader = threading.Thread(target=upload_worker, daemon=True)
    t_uploader.start()

    # Thread 5: 5-minute screenshot recorder (CCTV Timeline)
    t_shot = threading.Thread(target=five_minute_screenshot_worker, daemon=True)
    t_shot.start()

    # Thread 6 (Main Thread): Video Recorder Worker
    video_recorder_worker()
