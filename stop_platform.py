from __future__ import annotations

import os
import subprocess
import sys

import psutil

MARKERS = ("run_control.py", "run_worker.py", "open_platform.py")
PORTS = {8080, 9090}


def _cmd(proc: psutil.Process) -> str:
    try:
        return " ".join(proc.cmdline()).lower().replace("/", "\\")
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return ""


def _listens(proc: psutil.Process) -> bool:
    try:
        for conn in proc.net_connections(kind="inet"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port in PORTS:
                return True
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    return False


def _targets() -> list[psutil.Process]:
    me = os.getpid()
    found: dict[int, psutil.Process] = {}
    for proc in psutil.process_iter(["pid"]):
        if proc.pid == me:
            continue
        cmd = _cmd(proc)
        hit = any(m in cmd for m in MARKERS) or _listens(proc)
        if hit:
            found[proc.pid] = proc
    return list(found.values())


def _kill(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
        return
    try:
        proc = psutil.Process(pid)
        proc.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return


def main() -> None:
    targets = _targets()
    if not targets:
        print("Platform is not running.")
        return
    for proc in targets:
        print(f"stopping pid {proc.pid}")
        _kill(proc.pid)
    print("Platform stopped.")


if __name__ == "__main__":
    main()
