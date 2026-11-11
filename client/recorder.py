import os
import sys
import time
import json
import uuid
import socket
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
import numpy as np
import mss
import imageio

# Directories
CLIENT_DIR = Path(__file__).resolve().parent
BASE_DIR = CLIENT_DIR.parent
CONFIG_PATH = CLIENT_DIR / "client_config.json"
GLOBAL_CONFIG_PATH = BASE_DIR / "config.json"
TEMP_DIR = CLIENT_DIR / "temp_records"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

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
            cfg = {
                "computer_name": data.get("computer_name", "albayan 1"),
                "server_url": srv_url,
                "api_secret": data.get("api_secret", "secure_study_monitor_secret_key_8899"),
                "fps": data.get("fps", 10),
                "chunk_minutes": data.get("chunk_minutes", 2)
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            print(f"[Register] Auto-assigned Computer Name: {cfg['computer_name']}")
            return cfg
    except Exception as e:
        print(f"[Register] Could not connect to server for auto-registration: {e}")

    return {
        "computer_name": "albayan 1",
        "server_url": srv_url,
        "api_secret": "secure_study_monitor_secret_key_8899",
        "fps": 10,
        "chunk_minutes": 2
    }

def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if cfg.get("computer_name"):
                    return cfg
        except Exception:
            pass
    return auto_register_pc()

CONFIG = load_config()
COMPUTER_NAME = CONFIG.get("computer_name", "albayan 1").strip()
SERVER_URL = CONFIG.get("server_url", "http://127.0.0.1:8899").rstrip("/")
API_SECRET = CONFIG.get("api_secret", "secure_study_monitor_secret_key_8899")
FPS = CONFIG.get("fps", 10)
# 2-Minute Video Chunks (120 seconds) for fast web viewing
CHUNK_SECONDS = CONFIG.get("chunk_minutes", 2) * 60

upload_queue = queue.Queue()

# ----------------- 1. POPUP NOTIFICATION -----------------

def show_recording_popup():
    try:
        import tkinter as tk

        root = tk.Tk()
        root.title("Albayan Study Monitor")
        root.attributes("-topmost", True)
        root.overrideredirect(True)

        screen_width = root.winfo_screenwidth()
        w = 520
        h = 140
        x = (screen_width - w) // 2
        y = 35
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.configure(bg="#0f172a")

        frame = tk.Frame(root, bg="#1e293b", highlightbackground="#6366f1", highlightthickness=2, padx=16, pady=12)
        frame.pack(fill="both", expand=True)

        header_lbl = tk.Label(
            frame,
            text=f"⚠️  [{COMPUTER_NAME.upper()}] SCREEN RECORDING ACTIVE",
            font=("Segoe UI", 12, "bold"),
            fg="#f87171",
            bg="#1e293b"
        )
        header_lbl.pack(anchor="w")

        msg_lbl = tk.Label(
            frame,
            text=f"This computer ({COMPUTER_NAME}) is under screen recording for study monitoring.\nസ്ക്രീൻ റെക്കോർഡിംഗ് ആരംഭിച്ചിരിക്കുന്നു.",
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

# ----------------- 2. SAFE AUTO-UPDATER -----------------

def auto_updater_worker():
    time.sleep(30)
    while True:
        try:
            subprocess.run(["git", "fetch", "origin", "main"], cwd=str(BASE_DIR), capture_output=True, timeout=20)
            res = subprocess.run(["git", "status", "-uno"], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=10)
            if "Your branch is behind" in res.stdout:
                print(f"[{COMPUTER_NAME}] Safe Auto-Update: New code detected on GitHub. Pulling...")
                subprocess.run(["git", "pull", "--no-rebase", "origin", "main"], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=30)
                print(f"[{COMPUTER_NAME}] Updated successfully. Restarting recorder...")
                python = sys.executable
                os.execl(python, python, *sys.argv)
        except Exception:
            pass
        time.sleep(1800)

# ----------------- 3. UPLOADER & PING THREAD -----------------

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
        time.sleep(25)

def upload_worker():
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
                with open(path_obj, "rb") as f:
                    files = {"video": (path_obj.name, f, "video/mp4")}
                    data = {"computer_name": COMPUTER_NAME}
                    headers = {"X-API-Secret": API_SECRET}
                    res = requests.post(
                        f"{SERVER_URL}/api/client/upload",
                        files=files,
                        data=data,
                        headers=headers,
                        timeout=90
                    )
                    if res.status_code == 200:
                        uploaded = True
                        print(f"[Uploader] Successfully uploaded {path_obj.name} to server!")
                        try:
                            path_obj.unlink()
                        except Exception:
                            pass
            except Exception as e:
                time.sleep(retry_delay)
                retry_delay = min(60, retry_delay * 2)

        upload_queue.task_done()

# ----------------- 4. SCREEN RECORDER -----------------

def record_screen():
    print(f"[{COMPUTER_NAME}] Screen recorder active at {FPS} FPS (2-minute clips)...")
    
    # Enqueue any pending files from previous sessions
    for prev_file in TEMP_DIR.glob("*.mp4"):
        upload_queue.put(str(prev_file))

    with mss.MSS() as sct:
        mon = sct.monitors[1]
        width = mon["width"]
        height = mon["height"]

        # Ensure dimensions are divisible by 2 for H.264
        width = width if width % 2 == 0 else width - 1
        height = height if height % 2 == 0 else height - 1
        capture_box = {"top": mon["top"], "left": mon["left"], "width": width, "height": height}

        target_frame_time = 1.0 / FPS
        fallback_frame = np.zeros((height, width, 3), dtype=np.uint8)

        while True:
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            video_filename = f"[{COMPUTER_NAME}]_{timestamp_str}.mp4"
            current_video_path = TEMP_DIR / video_filename

            try:
                # Faststart flag ensures MP4 index is at front for instant browser playback
                writer = imageio.get_writer(
                    str(current_video_path),
                    fps=FPS,
                    codec="libx264",
                    quality=6,
                    pixelformat="yuv420p",
                    output_params=["-movflags", "+faststart"]
                )
            except Exception as err:
                print(f"[Recorder] Writer error: {err}")
                time.sleep(3)
                continue

            chunk_start_time = time.time()
            chunk_end_time = chunk_start_time + CHUNK_SECONDS
            frame_count = 0

            while time.time() < chunk_end_time:
                loop_start = time.time()
                try:
                    raw_frame = np.array(sct.grab(capture_box))
                    rgb_frame = raw_frame[:, :, [2, 1, 0]]
                    writer.append_data(rgb_frame)
                    frame_count += 1
                except Exception:
                    # If screen is locked or inactive, supply standby frame so video stream never drops
                    try:
                        writer.append_data(fallback_frame)
                        frame_count += 1
                    except Exception:
                        pass

                elapsed = time.time() - loop_start
                sleep_time = target_frame_time - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

            try:
                writer.close()
                file_size = current_video_path.stat().st_size if current_video_path.exists() else 0
                file_size_mb = round(file_size / (1024 * 1024), 2)
                print(f"[Recorder] 2-min chunk ready: {video_filename} ({frame_count} frames, {file_size_mb} MB)")
                
                if current_video_path.exists() and file_size > 1000:
                    upload_queue.put(str(current_video_path))
                else:
                    if current_video_path.exists():
                        current_video_path.unlink()
            except Exception as e:
                print(f"[Recorder] Error finalizing chunk: {e}")

# ----------------- MAIN FLOW -----------------

if __name__ == "__main__":
    print(f"[{COMPUTER_NAME}] Albayan Study Monitor. Initializing (10s delay)...")
    time.sleep(10)

    # Show warning popup
    show_recording_popup()

    # Start workers
    t_updater = threading.Thread(target=auto_updater_worker, daemon=True)
    t_updater.start()

    t_ping = threading.Thread(target=ping_worker, daemon=True)
    t_ping.start()

    t_upload = threading.Thread(target=upload_worker, daemon=True)
    t_upload.start()

    # Continuous recording
    record_screen()
