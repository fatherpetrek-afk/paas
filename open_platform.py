from __future__ import annotations

import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from control.config import PORT
from control.netinfo import access_info

ROOT = Path(__file__).resolve().parent
PYTHON = Path(sys.executable)


def port_open(port: int) -> bool:
    sock = socket.socket()
    sock.settimeout(0.3)
    try:
        sock.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def start_window(title: str, script: str) -> None:
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen(
        [str(PYTHON), str(ROOT / script)],
        cwd=ROOT,
        creationflags=flags,
    )
    print(f"started {title}")


def wait_ready(port: int, seconds: int = 20) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_open(port):
            return
        time.sleep(0.3)
    raise SystemExit(f"control plane did not start on port {port}")


def main() -> None:
    info = access_info()
    if not port_open(PORT):
        start_window("control", "run_control.py")
        start_window("worker", "run_worker.py")
        wait_ready(PORT)
    webbrowser.open(info["local_url"])


if __name__ == "__main__":
    main()
