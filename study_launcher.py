from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

HOST = "127.0.0.1"
PORT = 5602
URL = f"http://{HOST}:{PORT}/"


def _port_open(host=HOST, port=PORT, timeout=0.3):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _study_server_ready(timeout=0.5):
    try:
        with urlopen(f"{URL}health", timeout=timeout) as response:
            payload = json.load(response)
        return payload.get("status") == "ok" and payload.get("service") == "poker-study"
    except Exception:
        return False


def _server_command():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--study-server"]
    return [sys.executable, "-m", "pokerlab.webapi"]


def _stop(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=4)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _error(message):
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "Poker Study", 0x10)
    else:
        print(message, file=sys.stderr)


def main():
    if "--study-server" in sys.argv:
        from pokerlab.webapi import main as server_main
        server_main()
        return 0

    server = None
    if _port_open():
        if not _study_server_ready():
            _error(f"Port {PORT} is already used by another application.")
            return 1
    else:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        server = subprocess.Popen(_server_command(), cwd=root, creationflags=flags)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not _study_server_ready():
            if server.poll() is not None:
                _error("The local Poker Study server exited during startup.")
                return 1
            time.sleep(0.15)
        if not _study_server_ready():
            _stop(server)
            _error("The local Poker Study server did not start within 20 seconds.")
            return 1

    try:
        import webview
        webview.create_window("Poker Study", URL, width=1440, height=900, min_size=(760, 560))
        webview.start()
    finally:
        _stop(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
