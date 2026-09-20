from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from shared.protocol import GpuInfo, WorkerLocks


def detect_os() -> str:
    return {"nt": "windows", "posix": os.name}.get(os.name, os.name)


def host_os() -> str:
    import sys

    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def host_arch() -> str:
    import platform

    m = platform.machine().lower()
    if m in {"x86_64", "amd64"}:
        return "amd64"
    if m in {"aarch64", "arm64"}:
        return "arm64"
    return m or "unknown"


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,
            timeout=8,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def native_runtimes() -> list[str]:
    import sys

    from worker.toolchains import runtime_families

    out = [f"python:{sys.version_info.major}.{sys.version_info.minor}"]
    if shutil.which("node"):
        out.append("node")
    for family in runtime_families():
        if family not in out:
            out.append(family)
    return out


def collect_gpus() -> tuple[list[GpuInfo], list[float]]:
    if not shutil.which("nvidia-smi"):
        return [], []
    try:
        raw = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return [], []
    infos: list[GpuInfo] = []
    util: list[float] = []
    for line in raw.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        name, mem, u = parts[0], parts[1], parts[2]
        try:
            infos.append(GpuInfo(name=name, memory_mb=int(float(mem))))
            util.append(float(u))
        except ValueError:
            continue
    return infos, util


def cpu_mem() -> tuple[float, float, int]:
    import psutil

    vm = psutil.virtual_memory()
    return psutil.cpu_percent(interval=0.2), vm.percent, int(vm.total / (1024 * 1024))


def io_bytes() -> tuple[int, int]:
    import psutil

    n = psutil.net_io_counters()
    return int(n.bytes_sent), int(n.bytes_recv)


def load_locks(path: Path) -> WorkerLocks:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return WorkerLocks(
            run_open=bool(data.get("run_open", True)),
            security_open=bool(data.get("security_open", False)),
            admin_open=bool(data.get("admin_open", False)),
        )
    locks = WorkerLocks(
        run_open=os.environ.get("PAAS_RUN_LOCK", "open") != "closed",
        security_open=os.environ.get("PAAS_SECURITY_LOCK", "closed") == "open",
        admin_open=os.environ.get("PAAS_ADMIN_LOCK", "closed") == "open",
    )
    save_locks(path, locks)
    return locks


def save_locks(path: Path, locks: WorkerLocks) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(locks.model_dump_json(indent=2), encoding="utf-8")
