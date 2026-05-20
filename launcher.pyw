"""
WH-347 Audit Engine - Silent Launcher
Double-click the shortcut: server starts if needed, browser opens. No popup.
"""

import webbrowser
import socket
import subprocess
import sys
import os
import time

APP_URL  = "http://localhost:5000"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON   = sys.executable


def _server_up():
    try:
        s = socket.create_connection(("127.0.0.1", 5000), timeout=1)
        s.close()
        return True
    except OSError:
        return False


if not _server_up():
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [PYTHON, os.path.join(BASE_DIR, "app.py")],
        cwd=BASE_DIR,
        creationflags=flags,
    )
    for _ in range(30):
        time.sleep(0.5)
        if _server_up():
            break

webbrowser.open(APP_URL)
