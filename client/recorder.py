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
import subprocess
from pathlib import Path
from datetime import datetime

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import requests
from PIL import ImageGrab, Image
import mss
import numpy as np

# Directories
CLIENT_DIR = Path(__file__).resolve().parent
BASE_DIR = CLIENT_DIR.parent
CONFIG_PATH = CLIENT_DIR / "client_config.json"
GLOBAL_CONFIG_PATH = BASE_DIR / "config.json"
TEMP_DIR = CLIENT_DIR / "temp_records"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

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

def get_machine_id():
    try:
        return str(uuid.getnode())
    except Exception:
        return socket.gethostname()

def discover_server_url():
    candidates = ["http://127.0.0.1:8899", "http://192.168.1.3:8899"]
    if GLOBAL_CONFIG_PATH.exists():
        try:
            with open(GLOBAL_CONFIG_PATH, "r", encoding="utf-8") as f:
                g = json.load(f)
                sip = g.get("server_ip")
                sport = g.get("server_port", 8899)
                if sip:
                    candidates.insert(1, f"http://{sip}:{sport}")
        except Exception:
            pass

    for url in candidates:
        try:
            r = requests.get(f"{url}/api/status", timeout=1.5)
            if r.status_code in [200, 401]:
                return url
        except Exception:
            pass

    return "http://192.168.1.3:8899"

def auto_register_pc():
    dev_id = get_machine_id()
    srv_url = discover_server_url()
    try:
        res = requests.post(
            f"{srv_url}/api/client/register",
            json={"device_id": dev_id},
            timeout=5
        )
        if res.status_code == 200:
            data = res.json()
            raw_name = data.get("computer_name", "albayan 1")
            clean_name = normalize_pc_name(raw_name)
            cfg = {
                "computer_name": clean_name,
                "server_url": srv_url,
                "api_secret": data.get("api_secret", "secure_study_monitor_secret_key_8899"),
                "screenshot_interval_seconds": 300,
                "live_stream_interval_seconds": 5
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            print(f"[Register] Auto-assigned Computer Name: {cfg['computer_name']}")
            return cfg
    except Exception as e:
        print(f"[Register] Server connect error, using local default: {e}")

    return {
        "computer_name": "albayan 1",
        "server_url": srv_url,
        "api_secret": "secure_study_monitor_secret_key_8899",
        "screenshot_interval_seconds": 300,
        "live_stream_interval_seconds": 5
    }

def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if cfg.get("computer_name"):
                    cfg["computer_name"] = normalize_pc_name(cfg["computer_name"])
                    return cfg
        except Exception:
            pass
    return auto_register_pc()

CONFIG = load_config()
COMPUTER_NAME = normalize_pc_name(CONFIG.get("computer_name", "albayan 1"))
SERVER_URL = CONFIG.get("server_url", "http://127.0.0.1:8899").rstrip("/")
API_SECRET = CONFIG.get("api_secret", "secure_study_monitor_secret_key_8899")
SCREENSHOT_INTERVAL = int(CONFIG.get("screenshot_interval_seconds", 300)) # 5 minutes
LIVE_INTERVAL = int(CONFIG.get("live_stream_interval_seconds", 5)) # 5 seconds

# ----------------- 1. RELIABLE NON-BLACK SCREEN CAPTURE -----------------

def capture_desktop_image():
    """
    Captures Windows desktop screen reliably.
    Attaches thread to interactive desktop session to ensure NO BLACK SCREEN.
    """
    try:
        user32 = ctypes.windll.user32
        desk = user32.OpenInputDesktop(0, False, 0x01FF)
        if desk:
            user32.SetThreadDesktop(desk)
    except Exception:
        pass

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

# ----------------- 2. POPUP NOTIFICATION (OVERT) -----------------

def show_recording_popup():
    try:
        import tkinter as tk

        root = tk.Tk()
        root.title("Albayan Study Monitor")
        root.attributes("-topmost", True)
        root.overrideredirect(True)

        screen_width = root.winfo_screenwidth()
        w = 540
        h = 140
        x = (screen_width - w) // 2
        y = 35
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.configure(bg="#0f172a")

        frame = tk.Frame(root, bg="#1e293b", highlightbackground="#6366f1", highlightthickness=2, padx=16, pady=12)
        frame.pack(fill="both", expand=True)

        header_lbl = tk.Label(
            frame,
            text=f"⚠️  [{COMPUTER_NAME.upper()}] CCTV MONITORING ACTIVE",
            font=("Segoe UI", 12, "bold"),
            fg="#f87171",
            bg="#1e293b"
        )
        header_lbl.pack(anchor="w")

        msg_lbl = tk.Label(
            frame,
            text=f"This computer ({COMPUTER_NAME}) is under screen monitoring.\nസ്ക്രീൻ റെക്കോർഡിംഗ് ആരംഭിച്ചിരിക്കുന്നു (5-min snapshots active).",
            font=("Segoe UI", 10),
            fg="#cbd5e1",
            bg="#1e293b",
            justify="left"
        )
        msg_lbl.pack(anchor="w", pady=(4, 0))

        root.after(7000, root.destroy)
        root.mainloop()
    except Exception as e:
        print(f"[Popup] Notice: {e}")

def show_snapshot_toast():
    """
    Subtle, non-disturbing notification for the computer user:
    - User knows a 5-min snapshot was taken (study monitor overt awareness).
    - Positioned at bottom-right corner just above the taskbar.
    - Uses Windows SWP_NOACTIVATE: NEVER steals keyboard focus, mouse clicks, or interrupts games/typing!
    - Soft chime/click sound.
    - Auto-closes smoothly in 2.5 seconds.
    """
    try:
        import winsound
        winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        pass

    try:
        import tkinter as tk
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.92)

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        w, h = 330, 62
        x = sw - w - 20
        y = sh - h - 55

        root.geometry(f"{w}x{h}+{x}+{y}")
        root.configure(bg="#090d16")

        f = tk.Frame(root, bg="#111827", highlightbackground="#10b981", highlightthickness=1.5, padx=12, pady=8)
        f.pack(fill="both", expand=True)

        lbl1 = tk.Label(f, text="📸 CCTV SNAPSHOT CAPTURED", font=("Segoe UI", 9, "bold"), fg="#34d399", bg="#111827")
        lbl1.pack(anchor="w")

        lbl2 = tk.Label(f, text=f"[{COMPUTER_NAME.upper()}] 5-Min Screen Saved • പഠന നിരീക്ഷണം", font=("Segoe UI", 8), fg="#9ca3af", bg="#111827")
        lbl2.pack(anchor="w")

        # Crucial: Prevent stealing focus from current active window
        hwnd = root.winfo_id()
        user32 = ctypes.windll.user32
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        HWND_TOPMOST = -1
        user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)

        root.after(2500, root.destroy)
        root.mainloop()
    except Exception:
        pass

# ----------------- 3. LIVE CCTV STREAMER (EVERY 5 SECONDS) -----------------

def live_cctv_worker():
    """Sends a fast live thumbnail frame every 5 seconds to power the CCTV quad monitor."""
    print(f"[{COMPUTER_NAME}] Live CCTV streamer started (every {LIVE_INTERVAL}s)...")
    while True:
        try:
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
                requests.post(
                    f"{SERVER_URL}/api/client/live_frame",
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=5
                )
        except Exception:
            pass
        time.sleep(LIVE_INTERVAL)

# ----------------- 4. 5-MINUTE SCREENSHOT RECORDER -----------------

def five_minute_screenshot_worker():
    """Captures and uploads a high-resolution screenshot every 5 minutes."""
    print(f"[{COMPUTER_NAME}] 5-minute screenshot scheduler active...")
    while True:
        try:
            img = capture_desktop_image()
            if img:
                # Overt notification: computer user knows screen was captured (without focus steal / disturbance)
                threading.Thread(target=show_snapshot_toast, daemon=True).start()

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
    while True:
        try:
            requests.post(
                f"{SERVER_URL}/api/client/ping",
                headers={"X-API-Secret": API_SECRET},
                json={"computer_name": COMPUTER_NAME},
                timeout=5
            )
        except Exception:
            pass
        time.sleep(20)

# ----------------- 6. SAFE AUTO-UPDATER -----------------

def auto_updater_worker():
    time.sleep(30)
    while True:
        try:
            subprocess.run(["git", "fetch", "origin", "main"], cwd=str(BASE_DIR), capture_output=True, timeout=20)
            res = subprocess.run(["git", "status", "-uno"], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=10)
            if "Your branch is behind" in res.stdout:
                print(f"[{COMPUTER_NAME}] Safe Auto-Update: Pulling latest features from GitHub...")
                subprocess.run(["git", "pull", "--no-rebase", "origin", "main"], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=30)
                print(f"[{COMPUTER_NAME}] Updated successfully. Restarting...")
                python = sys.executable
                os.execl(python, python, *sys.argv)
        except Exception:
            pass
        time.sleep(1800)

# ----------------- MAIN FLOW -----------------

if __name__ == "__main__":
    print(f"=================================================")
    print(f"  ALBAYAN CCTV MONITOR CLIENT - [{COMPUTER_NAME}]")
    print(f"  Interval: Screenshot every 5 minutes")
    print(f"  Display: CCTV Quad Live Feed")
    print(f"=================================================")
    print(f"Initializing (10s startup delay)...")
    time.sleep(10)

    # Show warning popup
    show_recording_popup()

    # Thread 1: Live CCTV frame stream (every 5 seconds)
    t_live = threading.Thread(target=live_cctv_worker, daemon=True)
    t_live.start()

    # Thread 2: Ping heartbeat (every 20 seconds)
    t_ping = threading.Thread(target=ping_worker, daemon=True)
    t_ping.start()

    # Thread 3: Safe GitHub Auto-Updater
    t_updater = threading.Thread(target=auto_updater_worker, daemon=True)
    t_updater.start()

    # Thread 4 (Main thread): 5-minute screenshot recorder
    five_minute_screenshot_worker()
