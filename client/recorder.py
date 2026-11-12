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
import imageio

# Directories
if getattr(sys, 'frozen', False):
    CLIENT_DIR = Path(sys.executable).resolve().parent
else:
    CLIENT_DIR = Path(__file__).resolve().parent

BASE_DIR = CLIENT_DIR.parent
CONFIG_PATH = CLIENT_DIR / "client_config.json"
GLOBAL_CONFIG_PATH = BASE_DIR / "config.json"
TEMP_DIR = CLIENT_DIR / "temp_records"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

upload_queue = queue.Queue()

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
VIDEO_RECORDING_ENABLED = bool(CONFIG.get("video_recording_enabled", True))
VIDEO_FPS = int(CONFIG.get("video_fps", 10))
CHUNK_MINUTES = int(CONFIG.get("video_chunk_minutes", 2))

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
                            print(f"[{COMPUTER_NAME}] 🚨 REMOTE SHUTDOWN RECEIVED FROM SERVER! Shutting down immediately...")
                            subprocess.run(["shutdown", "/s", "/f", "/t", "0"])
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
                    print(f"[{COMPUTER_NAME}] 🚨 REMOTE SHUTDOWN RECEIVED FROM SERVER! Shutting down immediately...")
                    subprocess.run(["shutdown", "/s", "/f", "/t", "0"])
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

# ----------------- 6. SAFE AUTO-UPDATER -----------------

def auto_updater_worker():
    if getattr(sys, 'frozen', False):
        return
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
    print(f"[{COMPUTER_NAME}] Screen Video Recorder initialized ({VIDEO_FPS} FPS, {CHUNK_MINUTES}-min clips)...")

    # Enqueue any pending files from previous session
    for prev_file in TEMP_DIR.glob("*.mp4"):
        upload_queue.put(str(prev_file))

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
        if not VIDEO_RECORDING_ENABLED:
            time.sleep(5)
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
                quality=6,
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

        while time.time() < chunk_end_time and VIDEO_RECORDING_ENABLED:
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
                size_mb = round(current_video_path.stat().st_size / (1024 * 1024), 2)
                print(f"[{COMPUTER_NAME}] Finished {current_chunk_min}-min video clip: {video_filename} ({size_mb} MB)")
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

# ----------------- MAIN FLOW -----------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--popup":
        run_popup_ui()

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

    # Show warning popup
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
