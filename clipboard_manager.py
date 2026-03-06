import time
import threading
import tkinter as tk
import os
import pickle
import subprocess
import datetime
import logging
from pynput import keyboard
from AppKit import NSPasteboard, NSPasteboardTypeString, NSPasteboardTypePNG, \
                   NSPasteboardTypeTIFF, NSPasteboardTypeURL, NSPasteboardTypeFileURL
from Foundation import NSData, NSString, NSUTF8StringEncoding

# File path for persistence
BASE_DIR = os.path.expanduser("~/Documents/ClipboardManager")
HISTORY_FILE = os.path.join(BASE_DIR, "history.dat")
LOG_FILE = os.path.join(BASE_DIR, "clipboard_manager.log")
START_TIME = datetime.datetime.now().strftime("%I:%M %p")

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

def save_history():
    """Saves the current history to disk."""
    try:
        # We convert NSData to raw bytes so they can be 'pickled' (saved to disk)
        serializable_history = []
        for item in clipboard_history:
            serializable_snap = {}
            for t, nsdata in item["data"].items():
                serializable_snap[t] = bytes(nsdata)
            serializable_history.append({"data": serializable_snap, "time": item["time"]})
        
        with open(HISTORY_FILE, "wb") as f:
            pickle.dump(serializable_history, f)
    except Exception as e:
        logging.error(f"Save error: {e}", exc_info=True)

def load_history():
    """Loads history from disk on startup."""
    global clipboard_history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "rb") as f:
                loaded = pickle.load(f)
                for item in loaded:
                    nsdata_snap = {}
                    for t, b_data in item["data"].items():
                        nsdata_snap[t] = NSData.dataWithBytes_length_(b_data, len(b_data))
                    clipboard_history.append({"data": nsdata_snap, "time": item["time"]})
        except Exception as e:
            logging.error(f"Load error: {e}", exc_info=True)

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
