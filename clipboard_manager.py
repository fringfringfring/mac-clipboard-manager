import time
import threading
import tkinter as tk
import os
import pickle
import hmac
import hashlib
import secrets
import subprocess
import datetime
import logging
from pathlib import Path
from pynput import keyboard
from AppKit import NSPasteboard, NSPasteboardTypeString, NSPasteboardTypePNG, \
                   NSPasteboardTypeTIFF, NSPasteboardTypeURL, NSPasteboardTypeFileURL
from Foundation import NSData, NSString, NSUTF8StringEncoding

# File paths
BASE_DIR = os.path.expanduser("~/Documents/ClipboardManager")
LOG_FILE = os.path.join(BASE_DIR, "clipboard_manager.log")
APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "MacClipboardManager"
HISTORY_FILE = APP_SUPPORT_DIR / "history.dat"
KEY_FILE = APP_SUPPORT_DIR / "key.bin"
START_TIME = datetime.datetime.now().strftime("%I:%M %p")

# History file format
MAGIC = b"MCBM"               # 4-byte identifier
VERSION = 1                   # 1-byte format version
MAC_LEN = 32                  # SHA-256 digest size
HEADER_LEN = 4 + 1 + MAC_LEN  # magic + version + hmac

# Logging: writes to both terminal and a persistent log file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ]
)

# Store the last 3 snapshots
clipboard_history = []
is_internal_update = False
current_keys = set()
_lock = threading.Lock()

def _load_or_create_key() -> bytes:
    """Returns the HMAC key, generating and storing it on first run."""
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()
    key = secrets.token_bytes(32)
    fd = os.open(str(KEY_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    logging.info("Generated new HMAC key.")
    return key

def save_history():
    """Saves the current history to disk, HMAC-signed and written atomically."""
    try:
        # Convert NSData to raw bytes so they can be pickled
        serializable_history = []
        for item in clipboard_history:
            serializable_snap = {}
            for t, nsdata in item["data"].items():
                serializable_snap[t] = bytes(nsdata)
            serializable_history.append({"data": serializable_snap, "time": item["time"]})

        key = _load_or_create_key()
        payload = pickle.dumps(serializable_history, protocol=pickle.HIGHEST_PROTOCOL)
        mac = hmac.new(key, payload, hashlib.sha256).digest()

        tmp = HISTORY_FILE.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            f.write(MAGIC + bytes([VERSION]) + mac + payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, HISTORY_FILE)
    except Exception as e:
        logging.error(f"Save error: {e}", exc_info=True)

def load_history():
    """Loads history from disk, verifying HMAC before unpickling."""
    global clipboard_history
    if not HISTORY_FILE.exists():
        return
    try:
        key = _load_or_create_key()
        blob = HISTORY_FILE.read_bytes()

        if len(blob) < HEADER_LEN or blob[:4] != MAGIC:
            raise ValueError("Invalid history file format")

        ver = blob[4]
        if ver != VERSION:
            raise ValueError(f"Unsupported history file version: {ver}")

        stored_mac = blob[5:5 + MAC_LEN]
        payload = blob[5 + MAC_LEN:]

        expected_mac = hmac.new(key, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(stored_mac, expected_mac):
            raise ValueError("HMAC verification failed — history may have been tampered with")

        loaded = pickle.loads(payload)
        for item in loaded:
            nsdata_snap = {}
            for t, b_data in item["data"].items():
                nsdata_snap[t] = NSData.dataWithBytes_length_(b_data, len(b_data))
            clipboard_history.append({"data": nsdata_snap, "time": item["time"]})
    except Exception as e:
        logging.error(f"Load error: {e}", exc_info=True)
        try:
            HISTORY_FILE.unlink()
        except OSError:
            pass

def get_clipboard_snapshot():
    pb = NSPasteboard.generalPasteboard()
    types = pb.types()
    if not types: return None
    snapshot = {}
    for t in types:
        data = pb.dataForType_(t)
        if data:
            snapshot[t] = NSData.dataWithData_(data)
    return snapshot

def monitor_clipboard():
    global clipboard_history, is_internal_update
    pb = NSPasteboard.generalPasteboard()
    last_change_count = pb.changeCount()
    
    while True:
        try:
            current_change_count = pb.changeCount()
            if current_change_count != last_change_count:
                last_change_count = current_change_count
                skip = False
                with _lock:
                    if is_internal_update:
                        is_internal_update = False
                        skip = True
                if skip:
                    time.sleep(0.5)
                    continue

                snapshot = get_clipboard_snapshot()
                if snapshot:
                    is_dup = False
                    with _lock:
                        if clipboard_history:
                            s1 = snapshot.get(NSPasteboardTypeString)
                            s2 = clipboard_history[0]["data"].get(NSPasteboardTypeString)
                            if s1 and s2 and s1.isEqualToData_(s2):
                                is_dup = True

                    if not is_dup:
                        with _lock:
                            clipboard_history.insert(0, {"data": snapshot, "time": time.time()})
                            clipboard_history = clipboard_history[:3]
                        save_history() # Save to disk whenever something new is copied
        except Exception:
            logging.exception("Unexpected error in clipboard monitor")
        time.sleep(0.5)

def select_item(snapshot):
    global is_internal_update
    with _lock:
        is_internal_update = True
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    types = list(snapshot.keys())
    pb.declareTypes_owner_(types, None)
    for t, data in snapshot.items():
        pb.setData_forType_(data, t)
    subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff"])

def get_relative_time(timestamp):
    diff = int(time.time() - timestamp)
    if diff < 60: return f"{diff}s ago"
    if diff < 3600: return f"{diff // 60}m ago"
    return f"{diff // 3600}h ago"

def get_label_for_snapshot(item):
    snapshot = item["data"]
    time_str = get_relative_time(item["time"])
    if NSPasteboardTypeString in snapshot:
        nsdata = snapshot[NSPasteboardTypeString]
        nsstring = NSString.alloc().initWithData_encoding_(nsdata, NSUTF8StringEncoding)
        text = str(nsstring) if nsstring else ""
        clean = text.replace('\n', ' ').strip()
        label_text = (clean[:30] + "...") if len(clean) > 30 else (clean or "[Empty]")
    elif NSPasteboardTypeFileURL in snapshot: label_text = "[FILE/FOLDER]"
    elif NSPasteboardTypePNG in snapshot or NSPasteboardTypeTIFF in snapshot: label_text = "[IMAGE]"
    else: label_text = "[RICH DATA]"
    return f"{label_text} ({time_str})"

def show_popup_menu(event=None):
    menu = tk.Menu(root, tearoff=0, font=("System", 14))
    with _lock:
        history_copy = list(clipboard_history)
    if not history_copy:
        menu.add_command(label="Clipboard is empty", state="disabled")
    else:
        for i, item in enumerate(history_copy):
            label = f"{i+1}. {get_label_for_snapshot(item)}"
            menu.add_command(label=label, command=lambda s=item["data"]: select_item(s))
    
    menu.add_separator()
    menu.add_command(label=f"Service started at {START_TIME}", state="disabled")

    x, y = root.winfo_pointerx(), root.winfo_pointery()
    try:
        menu.tk_popup(x, y)
    finally:
        menu.grab_release()

def on_press(key):
    try:
        if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r: current_keys.add('ctrl')
        elif key in (keyboard.Key.shift, keyboard.Key.shift_r): current_keys.add('shift')
        elif hasattr(key, 'char') and key.char == 'v': current_keys.add('v')
        if 'ctrl' in current_keys and 'shift' in current_keys and 'v' in current_keys:
            root.event_generate("<<ShowMenu>>")
    except Exception: pass

def on_release(key):
    try:
        if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r: current_keys.discard('ctrl')
        elif key in (keyboard.Key.shift, keyboard.Key.shift_r): current_keys.discard('shift')
        elif hasattr(key, 'char') and key.char == 'v': current_keys.discard('v')
    except Exception: pass

# Startup
load_history()
root = tk.Tk()
root.withdraw()
root.bind("<<ShowMenu>>", lambda e: show_popup_menu())
threading.Thread(target=monitor_clipboard, daemon=True).start()
keyboard.Listener(on_press=on_press, on_release=on_release).start()

logging.info(f"Persistent Clipboard Manager started at {START_TIME}")
try:
    root.mainloop()
except KeyboardInterrupt:
    logging.info("Exiting...")
