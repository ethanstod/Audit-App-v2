"""
WH-347 Audit Engine - Windows application entry point.

When compiled with PyInstaller this IS the exe.
- Starts the Flask server in a background thread via waitress.
- Opens the browser automatically.
- Sits in the system tray so the server keeps running until the user exits.
"""

import sys
import os
import subprocess
import threading
import webbrowser
import time
import socket

# ---------------------------------------------------------------------------
# Resolve paths before importing app so it picks up the right directories
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    _DATA_DIR     = os.path.dirname(sys.executable)
    _RESOURCE_DIR = sys._MEIPASS
else:
    _DATA_DIR     = os.path.dirname(os.path.abspath(__file__))
    _RESOURCE_DIR = _DATA_DIR

os.environ["WH347_DATA_DIR"]     = _DATA_DIR
os.environ["WH347_RESOURCE_DIR"] = _RESOURCE_DIR

from app import app as flask_app  # noqa: E402  (import after env setup)

# ---------------------------------------------------------------------------
PORT = 5000
URL  = f"http://127.0.0.1:{PORT}"


def _open_window():
    """Open in a standalone app window (Edge/Chrome app mode) — no browser tabs."""
    _edge = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    _chrome = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    _flags = [f"--app={URL}", "--window-size=1280,900", "--disable-extensions"]

    for exe in _edge + _chrome:
        if os.path.exists(exe):
            try:
                subprocess.Popen([exe] + _flags)
                return
            except Exception:
                continue

    webbrowser.open_new(URL)


def _server_up() -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", PORT), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def _run_server():
    try:
        from waitress import serve
        serve(flask_app, host="127.0.0.1", port=PORT, threads=4)
    except Exception:
        flask_app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


# ---------------------------------------------------------------------------
# System tray icon
# ---------------------------------------------------------------------------

def _make_icon_image():
    from PIL import Image, ImageDraw
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d    = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=12, fill="#0d1b2a")
    d.rounded_rectangle([0, 0, size - 1, 22],        radius=12, fill="#2563eb")
    return img


def _run_tray():
    try:
        import pystray

        def on_open(icon, item):
            _open_window()

        def on_exit(icon, item):
            icon.stop()
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("Open WH-347 Audit", on_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Stop Server & Exit", on_exit),
        )
        icon = pystray.Icon("WH347AuditEngine", _make_icon_image(),
                            "WH-347 Audit Engine", menu)
        icon.run()

    except Exception:
        # Fallback if pystray/Pillow unavailable: block until Ctrl-C
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    already_running = _server_up()

    if not already_running:
        t = threading.Thread(target=_run_server, daemon=True)
        t.start()
        for _ in range(30):      # wait up to 15 s
            time.sleep(0.5)
            if _server_up():
                break

    webbrowser.open(URL)

    if not already_running:
        _run_tray()              # blocks until user clicks "Stop Server & Exit"
