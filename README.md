# macOS Rich Clipboard Manager

A lightweight, persistent clipboard manager for macOS written in Python. It silently runs in the background, tracks your last 3 copied items (text, images, and files), and lets you paste any of them via a global hotkey.

---

## Features

- **Multi-type clipboard history** — captures text, images (PNG/TIFF), and file/folder paths
- **Persistent across restarts** — history is saved to disk and reloaded when the script starts again
- **Global hotkey** — press `Ctrl + Shift + V` anywhere to open a popup menu at your cursor
- **Duplicate suppression** — consecutive copies of the same text are not recorded twice
- **Audio feedback** — plays a soft system sound (Tink) when you select an item
- **Minimal footprint** — no menu bar icon, no GUI window; runs entirely in the background

---

## Requirements

- macOS (uses native `AppKit` / `NSPasteboard` APIs)
- Python 3.8+

---

## Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/fringfringfring/mac-clipboard-manager.git
   cd mac-clipboard-manager
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

   Dependencies:
   | Package | Purpose |
   |---------|---------|
   | `pynput` | Global keyboard listener for the hotkey |
   | `pyobjc-framework-Cocoa` | Access to macOS `AppKit` and `Foundation` (clipboard APIs) |

3. **Grant Accessibility permissions**

   `pynput` requires macOS Accessibility access to listen for global key events.
   Go to **System Settings > Privacy & Security > Accessibility** and add your Terminal (or Python) to the list.

---

## Usage

Run the script in any terminal:

```bash
python3 clipboard_manager.py
```

You will see:

```
Persistent Clipboard Manager started at HH:MM AM/PM
```

The script then runs silently in the background.

### Hotkey

Press **`Ctrl + Shift + V`** from any application to open a popup menu near your cursor. The menu shows up to 3 recent clipboard entries, each with a preview and a relative timestamp (e.g. `5s ago`, `3m ago`).

Click any entry to load it back onto the clipboard, then paste normally with `Cmd + V`.

### Menu preview format

| Content type | Preview shown |
|---|---|
| Text | First 30 characters of the text |
| Image | `[IMAGE]` |
| File / Folder | `[FILE/FOLDER]` |
| Other rich data | `[RICH DATA]` |

---

## Running at Login (Auto-start)

To have the clipboard manager start automatically when you log in, you can use a **launchd plist**.

1. Create `~/Library/LaunchAgents/com.user.clipboardmanager.plist`:

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
     "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
     <key>Label</key>
     <string>com.user.clipboardmanager</string>
     <key>ProgramArguments</key>
     <array>
       <string>/usr/bin/python3</string>
       <string>/Users/YOUR_USERNAME/Documents/ClipboardManager/clipboard_manager.py</string>
     </array>
     <key>RunAtLoad</key>
     <true/>
     <key>StandardOutPath</key>
     <string>/Users/YOUR_USERNAME/Documents/ClipboardManager/out.log</string>
     <key>StandardErrorPath</key>
     <string>/Users/YOUR_USERNAME/Documents/ClipboardManager/err.log</string>
   </dict>
   </plist>
   ```

2. Load it:

   ```bash
   launchctl load ~/Library/LaunchAgents/com.user.clipboardmanager.plist
   ```

3. To unload / stop it:

   ```bash
   launchctl unload ~/Library/LaunchAgents/com.user.clipboardmanager.plist
   ```

---

## How It Works

1. **Clipboard monitoring** — a background thread polls `NSPasteboard.changeCount()` every 500 ms. When the count changes and the update is not self-triggered, a full snapshot of all pasteboard types is captured.

2. **Snapshot storage** — each snapshot stores the raw `NSData` for every pasteboard type (text, image, URL, etc.), preserving full fidelity. Up to 3 snapshots are kept in memory.

3. **Persistence** — snapshots are serialized to `~/Documents/ClipboardManager/history.dat` using `pickle` after every new copy event. On startup, the file is loaded back so history survives restarts.

4. **Hotkey listener** — `pynput` listens globally for `Ctrl + Shift + V`. When triggered, a Tkinter virtual event (`<<ShowMenu>>`) is posted to the main thread, which opens a native `tk.Menu` popup at the current cursor position.

5. **Paste-back** — selecting a menu item calls `NSPasteboard.setData_forType_()` for every type in the snapshot, fully restoring the original clipboard contents. A flag prevents the monitor from re-recording this internal write.

---

## File Structure

```
ClipboardManager/
├── clipboard_manager.py      # Main script
├── requirements.txt          # Python dependencies
├── history.dat               # Auto-generated: persisted clipboard history (gitignored)
├── clipboard_manager.log     # Auto-generated: application log (gitignored)
├── out.log                   # Auto-generated: stdout log when run via launchd (gitignored)
├── err.log                   # Auto-generated: stderr log when run via launchd (gitignored)
└── README.md
```

---

## Privacy & Security

- **All data stays local.** This script has no network access. Your clipboard history never leaves your machine.
- **`history.dat` contains your clipboard data** in binary format. Treat it like any sensitive file — do not share it or commit it to version control. It is listed in `.gitignore` for this reason.
- **`pickle` is used for persistence.** Python's `pickle` format is not encrypted or signed. If someone with local access to your machine were to tamper with `history.dat`, it could execute arbitrary code the next time the script loads it. For a personal, single-user tool this risk is low, but you should be aware of it. If you want stronger guarantees, do not use this script on a shared machine.
- **Accessibility permission** is required by `pynput` to listen for global key events. This is a standard macOS mechanism — the script only acts on the specific `Ctrl + Shift + V` combination and does not record or transmit keystrokes.

---

## Limitations

- **macOS only** — relies on `AppKit` and `NSPasteboard`, which are not available on Windows or Linux.
- **3-item history** — the history cap is hardcoded. Change the slice `clipboard_history[:3]` in `clipboard_manager.py` to adjust.
- **Polling interval** — clipboard is checked every 500 ms. Very rapid copies within that window may be missed.
- **No tray icon** — there is no visual indicator that the manager is running; check Activity Monitor or your terminal.
