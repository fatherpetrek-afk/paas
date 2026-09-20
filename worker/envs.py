from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from worker.metrics import docker_available, host_os
from worker.toolchains import discover_tool_envs

_CACHE: dict = {"ts": 0.0, "envs": []}
TTL = 15.0

_NODE_BUILTIN = {
    "assert",
    "buffer",
    "child_process",
    "cluster",
    "console",
    "crypto",
    "dgram",
    "dns",
    "events",
    "fs",
    "http",
    "https",
    "net",
    "os",
    "path",
    "process",
    "querystring",
    "readline",
    "stream",
    "timers",
    "tls",
    "tty",
    "url",
    "util",
    "zlib",
}


def collect_environments(force: bool = False) -> list[dict]:
    now = time.time()
    if not force and _CACHE["envs"] and now - _CACHE["ts"] < TTL:
        return _CACHE["envs"]
    envs: list[dict] = []
    seen_exe: set[str] = set()
    for exe, label in _python_candidates():
        key = os.path.normcase(os.path.abspath(exe))
        if key in seen_exe:
            continue
        seen_exe.add(key)
        info = _python_env(exe, label)
        if info:
            envs.append(info)
    node = _node_env()
    if node:
        envs.append(node)
    envs.extend(discover_tool_envs())
    if docker_available():
        envs.append(
            {
                "id": "docker",
                "kind": "docker",
                "label": "Docker",
                "executable": "",
                "version": "docker",
                "packages": [],
            }
        )
    _CACHE["ts"] = now
    _CACHE["envs"] = envs
    return envs


def _python_exe(root: Path) -> Path | None:
    for cand in (root / "python.exe", root / "bin" / "python"):
        if cand.exists():
            return cand
    return None


def _conda_roots() -> list[Path]:
    homes = [Path.home()]
    profile = os.environ.get("USERPROFILE")
    if profile:
        homes.append(Path(profile))
    names = ("miniconda3", "anaconda3", "miniforge3", "mambaforge")
    out: list[Path] = []
    for home in homes:
        for name in names:
            out.append(home / name)
            out.append(home / name / "envs")
    for extra in (
        Path(r"C:\ProgramData\anaconda3"),
        Path(r"C:\ProgramData\miniconda3"),
        Path(os.environ.get("CONDA_PREFIX", "")),
        Path(os.environ.get("CONDA_ROOT", "")),
    ):
        if extra:
            out.append(extra)
            out.append(extra / "envs")
    return out


def _conda_info_envs() -> list[Path]:
    conda = shutil.which("conda") or shutil.which("conda.exe")
    if not conda:
        for root in _conda_roots():
            if root.name == "envs":
                continue
            for cand in (root / "Scripts" / "conda.exe", root / "condabin" / "conda.bat"):
                if cand.exists():
                    conda = str(cand)
                    break
            if conda:
                break
    if not conda:
        return []
    try:
        raw = subprocess.check_output(
            [conda, "env", "list", "--json"],
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL,
        )
        data = json.loads(raw or "{}")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return [Path(p) for p in (data.get("envs") or []) if p]


def _python_candidates() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = [(sys.executable, f"Python {sys.version_info.major}.{sys.version_info.minor} (this Worker)")]
    if host_os() == "windows":
        py = shutil.which("py")
        if py:
            try:
                raw = subprocess.check_output([py, "-0p"], text=True, timeout=6, stderr=subprocess.DEVNULL)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                raw = ""
            for line in raw.splitlines():
                parts = line.strip().rsplit(None, 1)
                if len(parts) == 2 and Path(parts[1]).exists():
                    out.append((parts[1], f"Python {parts[0].strip('- ')}"))
    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            out.append((found, name))
    seen: set[str] = set()
    for base in [*_conda_roots(), *_conda_info_envs()]:
        if not base.exists() or not base.is_dir():
            continue
        key = os.path.normcase(str(base.resolve()))
        if key in seen:
            continue
        seen.add(key)
        if base.name == "envs":
            for env in base.iterdir():
                exe = _python_exe(env)
                if exe:
                    out.append((str(exe), f"conda env {env.name}"))
            continue
        exe = _python_exe(base)
        if exe:
            out.append((str(exe), f"conda {base.name}"))
    return out


def _python_env(exe: str, label: str) -> dict | None:
    # Conda packages often import fine but omit importlib metadata, so also
    # inventory top-level names sitting in site-packages.
    code = r"""
import json, sys
from pathlib import Path
names = set(getattr(sys, "stdlib_module_names", ()))
try:
    from importlib.metadata import distributions, packages_distributions
    names.update(packages_distributions())
    for dist in distributions():
        n = (dist.metadata.get("Name") or "").strip()
        if n:
            names.add(n)
except Exception:
    pass
for raw in sys.path:
    root = Path(raw)
    low = str(root).replace("\\", "/").lower()
    if "site-packages" not in low and "dist-packages" not in low:
        continue
    if not root.is_dir():
        continue
    try:
        for item in root.iterdir():
            n = item.name
            if n.startswith(".") or n.endswith((".dist-info", ".egg-info", ".pth")):
                continue
            if n in {"__pycache__", "bin", "include"}:
                continue
            if item.is_dir():
                names.add(n)
            elif n.endswith((".py", ".pyd", ".so")):
                names.add(n.split(".")[0])
    except OSError:
        pass
print(json.dumps({"ver": sys.version.split()[0], "pkgs": sorted(names)}))
"""
    try:
        raw = subprocess.check_output([exe, "-c", code], text=True, timeout=20, stderr=subprocess.DEVNULL)
        data = json.loads(raw)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    digest = hashlib.sha1(os.path.normcase(os.path.abspath(exe)).encode()).hexdigest()[:10]
    ver = str(data.get("ver") or "")
    return {
        "id": f"python-{digest}",
        "kind": "python",
        "label": f"{label} · {ver}" if ver not in label else label,
        "executable": os.path.abspath(exe),
        "version": ver,
        "packages": list(data.get("pkgs") or []),
        "extensions": [".py"],
    }


def _node_env() -> dict | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        ver = subprocess.check_output([node, "-v"], text=True, timeout=5, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        ver = ""
    pkgs = set(_NODE_BUILTIN)
    npm = shutil.which("npm")
    if npm:
        try:
            raw = subprocess.check_output(
                [npm, "list", "-g", "--depth=0", "--json"],
                text=True,
                timeout=10,
                stderr=subprocess.DEVNULL,
            )
            data = json.loads(raw or "{}")
            deps = data.get("dependencies") or {}
            pkgs.update(deps.keys())
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass
    return {
        "id": "node",
        "kind": "node",
        "label": f"Node {ver}".strip(),
        "executable": os.path.abspath(node),
        "version": ver,
        "packages": sorted(pkgs),
        "extensions": [".js", ".mjs", ".cjs"],
    }
