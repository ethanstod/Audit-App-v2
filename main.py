"""
WH-347 Audit Engine - Windows application entry point.

Starts the Flask/waitress server in a daemon thread, then opens a native
app window via pywebview (uses Windows built-in WebView2 engine).
Closing the window exits the process.
"""

import sys
import os
import threading
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
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not _server_up():
        t = threading.Thread(target=_run_server, daemon=True)
        t.start()
        for _ in range(30):
            time.sleep(0.5)
            if _server_up():
                break

    import webview
    webview.create_window(
        "WH-347 Audit Engine",
        URL,
        width=1280,
        height=900,
        min_size=(800, 600),
    )
    webview.start()  # blocks until window is closed → daemon thread exits
