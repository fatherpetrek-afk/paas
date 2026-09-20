from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass


@dataclass
class ProcSnap:
    pid: int | None = None
    cpu_percent: float = 0.0
    proc_count: int = 0
    docker_name: str | None = None
    suspended: bool = False


class JobProcess:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pid: int | None = None
        self._docker: str | None = None
        self._suspended = False
        self._ps = None
        self._stdin: list[str] = []
        self._ui_kind = ""
        self._ui_port = 0

    def push_stdin(self, text: str) -> None:
        with self._lock:
            self._stdin.append(str(text or ""))

    def drain_stdin(self) -> list[str]:
        with self._lock:
            items = list(self._stdin)
            self._stdin.clear()
            return items

    def attach(self, pid: int, docker_name: str | None = None) -> None:
        import psutil

        with self._lock:
            self._pid = pid
            self._docker = docker_name
            self._suspended = False
            try:
                self._ps = psutil.Process(pid)
                self._ps.cpu_percent(None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._ps = None

    def detach(self) -> None:
        with self._lock:
            if self._suspended:
                self._resume_unlocked()
            self._pid = None
            self._docker = None
            self._ps = None
            self._suspended = False
            self._stdin.clear()
            self._ui_kind = ""
            self._ui_port = 0

    def set_ui(self, kind: str, port: int) -> None:
        with self._lock:
            self._ui_kind = str(kind or "")
            self._ui_port = int(port or 0)

    def ui(self) -> tuple[str, int]:
        with self._lock:
            return self._ui_kind, self._ui_port

    def snapshot(self) -> ProcSnap:
        import psutil

        with self._lock:
            if self._pid is None:
                return ProcSnap()
            cpu = 0.0
            nproc = 1
            try:
                proc = self._ps if self._ps is not None else psutil.Process(self._pid)
                cpu = float(proc.cpu_percent(None) or 0.0)
                kids = proc.children(recursive=True)
                nproc = 1 + len(kids)
                for child in kids:
                    try:
                        cpu += float(child.cpu_percent(None) or 0.0)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            return ProcSnap(
                pid=self._pid,
                cpu_percent=cpu,
                proc_count=nproc,
                docker_name=self._docker,
                suspended=self._suspended,
            )

    def suspend(self) -> None:
        with self._lock:
            if self._pid is None or self._suspended:
                return
            if self._docker:
                subprocess.run(["docker", "pause", self._docker], capture_output=True, check=False)
            else:
                self._walk("suspend")
            self._suspended = True

    def resume(self) -> None:
        with self._lock:
            self._resume_unlocked()

    def _resume_unlocked(self) -> None:
        if self._pid is None or not self._suspended:
            return
        if self._docker:
            subprocess.run(["docker", "unpause", self._docker], capture_output=True, check=False)
        else:
            self._walk("resume")
        self._suspended = False

    def _walk(self, action: str) -> None:
        import psutil

        try:
            proc = psutil.Process(self._pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        targets = [proc, *proc.children(recursive=True)]
        for item in reversed(targets) if action == "suspend" else targets:
            try:
                getattr(item, action)()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
                continue


CURRENT = JobProcess()
