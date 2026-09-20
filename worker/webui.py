from __future__ import annotations

import os
import socket
import time
from pathlib import Path

from shared.webui import UI_KINDS, ui_kind_from_imports, ui_prefix

_SKIP_DIR = {"__pycache__", ".venv", "venv", "site-packages", "node_modules", ".git"}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def kind_from_workdir(workdir: Path, spec: dict | None = None) -> str:
    spec = spec or {}
    kind = str(spec.get("ui_kind") or "") or ui_kind_from_imports(spec.get("imports") or [])
    if kind:
        return kind
    found: list[str] = []
    root = Path(workdir)
    html = False
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part.lower() in _SKIP_DIR for part in path.parts):
            continue
        suf = path.suffix.lower()
        if suf in {".html", ".htm"}:
            html = True
            continue
        if suf != ".py":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        low = text.lower()
        for name in UI_KINDS:
            if name == "html":
                continue
            if f"import {name}" in low or f"from {name}" in low:
                found.append(name)
    return ui_kind_from_imports(found) or ("html" if html else "")


def ui_env(kind: str, port: int, job_id: str) -> dict[str, str]:
    prefix = ui_prefix(job_id)
    env = {
        "PAAS_UI_KIND": kind,
        "PAAS_UI_PORT": str(port),
        "PAAS_UI_PREFIX": prefix,
        "PAAS_UI_JOB": job_id,
        "BROWSER": "none",
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        "STREAMLIT_SERVER_HEADLESS": "true",
        "STREAMLIT_SERVER_ADDRESS": "127.0.0.1",
        "STREAMLIT_SERVER_PORT": str(port),
        "STREAMLIT_SERVER_ENABLE_CORS": "false",
        "STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION": "false",
        "GRADIO_SERVER_NAME": "127.0.0.1",
        "GRADIO_SERVER_PORT": str(port),
        "GRADIO_ANALYTICS_ENABLED": "False",
    }
    if prefix:
        env["STREAMLIT_SERVER_BASE_URL_PATH"] = prefix.lstrip("/")
        env["GRADIO_ROOT_PATH"] = prefix
        env["SCRIPT_NAME"] = prefix
        env["APPLICATION_ROOT"] = prefix
    return env


def html_cmd(python_exe: str, port: int) -> list[str]:
    return [python_exe or "python", "-m", "http.server", str(int(port)), "--bind", "127.0.0.1"]


def ensure_html_index(workdir: Path, hint: str = "") -> Path:
    root = Path(workdir)
    index = root / "index.html"
    if index.is_file():
        return index
    candidates: list[Path] = []
    if hint:
        p = Path(hint)
        if not p.is_absolute():
            p = root / hint
        if p.is_file() and p.suffix.lower() in {".html", ".htm"}:
            candidates.append(p)
    for path in sorted(root.rglob("*"), key=lambda item: (len(item.parts), str(item).replace("\\", "/"))):
        if not path.is_file() or path.suffix.lower() not in {".html", ".htm"}:
            continue
        if path.resolve() == index.resolve():
            continue
        if path not in candidates:
            candidates.append(path)
    if candidates:
        index.write_bytes(candidates[0].read_bytes())
    else:
        index.write_text("<!doctype html><title>job</title>\n", encoding="utf-8")
    return index


def streamlit_cmd(python_exe: str, script: str, port: int, prefix: str) -> list[str]:
    exe = python_exe or "python"
    path = prefix.lstrip("/")
    return [
        exe,
        "-m",
        "streamlit",
        "run",
        script,
        "--server.address",
        "127.0.0.1",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--server.enableCORS",
        "false",
        "--server.enableXsrfProtection",
        "false",
        "--browser.gatherUsageStats",
        "false",
        "--server.baseUrlPath",
        path,
    ]


def script_from_parts(parts: list[str], workdir: Path) -> str:
    skip = {"-m", "streamlit", "run", "-u"}
    for item in reversed(parts[1:]):
        if item in skip or item.startswith("-"):
            continue
        name = Path(item).name
        if name.lower() in {"python", "python.exe", "python3", "streamlit", "streamlit.exe"}:
            continue
        candidate = Path(item)
        if not candidate.is_absolute():
            candidate = workdir / item
        if candidate.is_file():
            return str(Path(item))
        return item
    for name in ("app.py", "main.py", "streamlit_app.py"):
        if (workdir / name).is_file():
            return name
    return "app.py"


def port_open(port: int) -> bool:
    sock = socket.socket()
    sock.settimeout(0.25)
    try:
        sock.connect(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def wait_ui(port: int, stop) -> bool:
    deadline = time.time() + 90
    while time.time() < deadline:
        if callable(stop) and stop():
            return False
        if port_open(port):
            return True
        time.sleep(0.25)
    return False
