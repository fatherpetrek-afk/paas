from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

from shared.protocol import DEFAULT_TIMEOUT_SEC, JobManifest, ResourceLimits
from worker.jobproc import CURRENT
from worker.toolchains import recipe_for_exe
from worker.webui import (
    ensure_html_index,
    free_port,
    html_cmd,
    kind_from_workdir,
    script_from_parts,
    streamlit_cmd,
    ui_env,
    wait_ui,
)


LogFn = Callable[[str, str], None]
OnOutput = Callable[[str, Path], None]


def unpack(zip_path: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    return _job_root(dest)


def _job_root(dest: Path) -> Path:
    def hits(name: str) -> list[Path]:
        found = [p for p in dest.rglob(name) if p.is_file() and "__MACOSX" not in p.parts]
        found.sort(key=lambda p: (len(p.relative_to(dest).parts), str(p).replace("\\", "/")))
        return found

    projects = hits("project.json")
    if projects:
        return projects[0].parent
    manifests = hits("manifest.json")
    if not manifests:
        raise FileNotFoundError("project.json/manifest.json missing after unpack")
    return manifests[0].parent


def _load_project(workdir: Path) -> dict | None:
    path = workdir / "project.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def run_job(
    *,
    workdir: Path,
    manifest: JobManifest,
    has_docker: bool,
    native_runtimes: list[str],
    limits: ResourceLimits | None,
    log: LogFn,
    stop_event: Callable[[], bool] | None = None,
    job_id: str = "",
    python_exe: str | None = None,
    on_output: OnOutput | None = None,
) -> int:
    family = manifest.runtime.split(":")[0]
    native_ok = bool(python_exe) or manifest.runtime in native_runtimes or family in native_runtimes or any(
        r == family or r.startswith(family + ":") for r in native_runtimes
    )
    spec = _load_project(workdir)
    runs = [r for r in (spec or {}).get("runs") or [] if isinstance(r, dict) and (r.get("entry") or r.get("file"))]
    if not runs:
        runs = [{"file": "", "entry": manifest.entry}]
    timeout_left = max(1, int(manifest.timeout_sec or DEFAULT_TIMEOUT_SEC))
    total = len(runs)
    for i, run in enumerate(runs, 1):
        if stop_event and stop_event():
            return 137
        entry = str(run.get("entry") or "").strip() or manifest.entry
        sources = [str(s).replace("\\", "/") for s in (run.get("sources") or []) if s]
        one = manifest.model_copy(update={"entry": entry, "timeout_sec": timeout_left})
        if total > 1:
            log("system", f"run {i}/{total}: {run.get('file') or entry}")
        started = time.monotonic()
        if native_ok:
            code = _native(
                workdir,
                one,
                limits,
                log,
                stop_event,
                python_exe,
                extra_sources=sources,
                on_output=on_output,
                job_id=job_id,
            )
        elif has_docker:
            code = _docker(workdir, one, limits, log, stop_event, f"{job_id}-{i}", on_output=on_output)
        else:
            raise RuntimeError(f"no executor for runtime {manifest.runtime}")
        timeout_left = max(1, timeout_left - int(time.monotonic() - started))
        if code != 0:
            return code
    return 0


def collect_output(workdir: Path, dest_zip: Path) -> bool:
    out_dir = workdir / "output"
    if not out_dir.exists():
        return False
    shutil.make_archive(str(dest_zip.with_suffix("")), "zip", out_dir)
    return dest_zip.exists()


def _docker(
    workdir: Path,
    manifest: JobManifest,
    limits: ResourceLimits | None,
    log: LogFn,
    stop_event: Callable[[], bool] | None,
    job_id: str,
    on_output: OnOutput | None = None,
) -> int:
    slug = "".join(ch if ch.isalnum() or ch in "_.-" else "-" for ch in (job_id or "job"))[:40]
    name = f"paas-{slug or 'job'}"
    cmd = ["docker", "run", "--rm", "--name", name, "-v", f"{workdir.as_posix()}:/job", "-w", "/job"]
    if limits:
        if limits.cpu_cores:
            cmd += ["--cpus", str(limits.cpu_cores)]
        if limits.memory_mb:
            cmd += ["--memory", f"{limits.memory_mb}m"]
        if limits.gpu_count:
            cmd += ["--gpus", str(limits.gpu_count)]
    cmd += ["-e", "PYTHONPATH=/job"]
    cmd += [manifest.runtime, "sh", "-c", manifest.entry]
    log("system", "docker: " + " ".join(cmd))
    return _stream(
        cmd, workdir, log, timeout=manifest.timeout_sec, stop_event=stop_event, docker_name=name, on_output=on_output
    )


def _native(
    workdir: Path,
    manifest: JobManifest,
    limits: ResourceLimits | None,
    log: LogFn,
    stop_event: Callable[[], bool] | None,
    python_exe: str | None = None,
    extra_sources: list[str] | None = None,
    on_output: OnOutput | None = None,
    job_id: str = "",
) -> int:
    import sys

    del limits
    family = manifest.runtime.split(":")[0]
    exe = python_exe or ""
    parts = manifest.entry.split()
    hint = parts[-1] if parts else ""
    spec = _load_project(workdir)
    ui_kind = kind_from_workdir(workdir, spec) if (family == "python" or (parts and Path(parts[0]).name.lower() in {"python", "python3", "python.exe"})) else ""
    extra_env: dict[str, str] = {}
    if ui_kind and job_id:
        port = free_port()
        extra_env.update(ui_env(ui_kind, port, job_id))
        log("system", f"app on 127.0.0.1:{port}")
    if family == "python" or (parts and Path(parts[0]).name.lower() in {"python", "python3", "python.exe"}):
        if parts and Path(parts[0]).name.lower() in {"python", "python3", "python.exe"}:
            parts[0] = exe or sys.executable
        else:
            parts = [exe or sys.executable, hint or "main.py"]
        if ui_kind == "streamlit" and extra_env.get("PAAS_UI_PORT"):
            script = script_from_parts(parts, workdir)
            parts = streamlit_cmd(
                exe or sys.executable,
                script,
                int(extra_env["PAAS_UI_PORT"]),
                extra_env.get("PAAS_UI_PREFIX") or "",
            )
        elif ui_kind == "html" and extra_env.get("PAAS_UI_PORT"):
            ensure_html_index(workdir, hint)
            parts = html_cmd(exe or sys.executable, int(extra_env["PAAS_UI_PORT"]))
        py_env = _pythonpath(workdir)
        py_env.update(extra_env)
        log("system", "native: " + " ".join(parts))
        return _stream(
            parts,
            workdir,
            log,
            timeout=manifest.timeout_sec,
            stop_event=stop_event,
            env=py_env,
            on_output=on_output,
        )
    compiled = _invoke_cmd(family, workdir, exe, hint, extra_sources)
    if compiled is not None:
        build, run = compiled
        if build:
            log("system", "compile: " + " ".join(build))
            code = _stream(
                build,
                workdir,
                log,
                timeout=min(manifest.timeout_sec, 120),
                stop_event=stop_event,
                on_output=on_output,
            )
            if code != 0:
                return code
            if stop_event and stop_event():
                return 137
        log("system", "run: " + " ".join(run))
        return _stream(run, workdir, log, timeout=manifest.timeout_sec, stop_event=stop_event, on_output=on_output)
    if exe and parts:
        if Path(parts[0]).name.lower() in {Path(exe).stem.lower(), family}:
            parts[0] = exe
        else:
            parts = [exe] + parts[1:]
        log("system", "native: " + " ".join(parts))
        return _stream(parts, workdir, log, timeout=manifest.timeout_sec, stop_event=stop_event, on_output=on_output)
    log("system", f"native shell: {manifest.entry} (cwd={workdir})")
    if os.name == "nt":
        cmd = ["cmd", "/c", manifest.entry]
    else:
        cmd = ["sh", "-c", manifest.entry]
    return _stream(cmd, workdir, log, timeout=manifest.timeout_sec, stop_event=stop_event, on_output=on_output)


def _find_source(workdir: Path, exts: tuple[str, ...], hint: str) -> Path | None:
    if hint:
        direct = workdir / hint
        if direct.exists():
            return direct
        matches = list(workdir.rglob(Path(hint).name))
        if matches:
            return matches[0]
    files = [p for p in workdir.rglob("*") if p.suffix.lower() in exts and p.is_file()]
    if not files:
        return None
    preferred = {"main", "app", "run", "program"}
    hits = [p for p in files if p.stem.lower() in preferred]
    return hits[0] if hits else sorted(files, key=lambda p: (len(p.parts), str(p)))[0]


def _invoke_cmd(
    family: str,
    workdir: Path,
    exe: str,
    hint: str,
    extra_sources: list[str] | None = None,
) -> tuple[list[str] | None, list[str]] | None:
    spec = recipe_for_exe(exe, family)
    if not spec:
        return None
    out = workdir / ("paas_job.exe" if os.name == "nt" else "paas_job")
    src = _find_source(workdir, tuple(spec.get("exts") or ()), hint)
    if src is None and spec.get("mode") != "run":
        return None
    src = src or workdir
    srcs: list[str] = []
    for item in extra_sources or []:
        path = workdir / str(item)
        if path.is_file():
            srcs.append(str(path))
    if not srcs and getattr(src, "is_file", lambda: False)():
        srcs = [str(src)]
    mapping = {
        "{exe}": exe,
        "{src}": str(src),
        "{out}": str(out),
        "{dir}": str(workdir),
        "{srcdir}": str(src.parent if hasattr(src, "parent") else workdir),
        "{stem}": src.stem if hasattr(src, "stem") else "main",
    }

    def fill(parts: list[str]) -> list[str]:
        rendered = []
        for part in parts:
            if part == "{srcs}":
                rendered.extend(srcs or [str(src)])
                continue
            for key, val in mapping.items():
                part = part.replace(key, val)
            rendered.append(part)
        return rendered

    compile_cmd = fill(spec["compile"]) if spec.get("compile") else None
    run_cmd = fill(spec.get("run") or ["{out}"])
    return compile_cmd, run_cmd


def _kill(proc: subprocess.Popen, docker_name: str | None) -> None:
    if docker_name and shutil.which("docker"):
        subprocess.run(["docker", "rm", "-f", docker_name], capture_output=True, check=False)
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        proc.kill()


def _wait(proc: subprocess.Popen, timeout: float = 5) -> None:
    try:
        proc.wait(timeout=timeout)
    except Exception:
        pass


HOOKS = Path(__file__).resolve().parent / "pyhooks"
LIVE_MAX = 8 * 1024 * 1024


def _pythonpath(workdir: Path) -> dict[str, str]:
    old = os.environ.get("PYTHONPATH", "")
    parts = [str(HOOKS), str(workdir)]
    if old:
        parts.append(old)
    return {
        "PYTHONPATH": os.pathsep.join(parts),
        "PYTHONUNBUFFERED": "1",
        "MPLBACKEND": "Agg",
    }


def _flush_output(
    cwd: Path,
    seen: dict[str, tuple[int, int]],
    sent_at: dict[str, float],
    on_output: OnOutput | None,
) -> None:
    if on_output is None:
        return
    out = cwd / "output"
    if not out.is_dir():
        return
    now = time.monotonic()
    for path in out.rglob("*"):
        if not path.is_file():
            continue
        key = str(path)
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_size > LIVE_MAX:
            seen[key] = (st.st_mtime_ns, st.st_size)
            continue
        sig = (st.st_mtime_ns, st.st_size)
        if seen.get(key) == sig:
            continue
        if now - sent_at.get(key, 0.0) < 0.25:
            continue
        rel = path.relative_to(out).as_posix()
        try:
            on_output(rel, path)
        except Exception:
            continue
        seen[key] = sig
        sent_at[key] = now


def _watch_ui(port: int, kind: str, stop_event: Callable[[], bool] | None, proc: subprocess.Popen) -> None:
    def stopped() -> bool:
        if proc.poll() is not None:
            return True
        return bool(stop_event and stop_event())

    if wait_ui(port, stopped):
        CURRENT.set_ui(kind, port)



def _stream(
    cmd: list[str],
    cwd: Path,
    log: LogFn,
    timeout: int,
    stop_event: Callable[[], bool] | None = None,
    docker_name: str | None = None,
    env: dict[str, str] | None = None,
    on_output: OnOutput | None = None,
) -> int:
    import threading

    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env_map = os.environ.copy()
    env_map.setdefault("PYTHONUNBUFFERED", "1")
    env_map.setdefault("MPLBACKEND", "Agg")
    if env:
        env_map.update(env)
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        creationflags=flags,
        env=env_map,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    def pump(pipe, stream: str) -> None:
        for line in iter(pipe.readline, ""):
            log(stream, line.rstrip("\r\n"))
        pipe.close()

    threads = [
        threading.Thread(target=pump, args=(proc.stdout, "stdout"), daemon=True),
        threading.Thread(target=pump, args=(proc.stderr, "stderr"), daemon=True),
    ]
    for t in threads:
        t.start()
    CURRENT.attach(proc.pid, docker_name)
    port = int((env_map.get("PAAS_UI_PORT") or 0) or 0)
    kind = env_map.get("PAAS_UI_KIND") or ""
    if port > 0 and kind:
        threading.Thread(
            target=_watch_ui,
            args=(port, kind, stop_event, proc),
            daemon=True,
            name="paas-ui-wait",
        ).start()
    left = float(timeout)
    last = time.time()
    seen: dict[str, tuple[int, int]] = {}
    sent_at: dict[str, float] = {}
    try:
        while proc.poll() is None:
            now = time.time()
            dt = now - last
            last = now
            if stop_event and stop_event():
                _kill(proc, docker_name)
                _wait(proc)
                log("system", "stopped; Worker released the process")
                return 137
            for chunk in CURRENT.drain_stdin():
                if proc.stdin is None:
                    break
                try:
                    proc.stdin.write(chunk if chunk.endswith("\n") else chunk + "\n")
                    proc.stdin.flush()
                except BrokenPipeError:
                    break
            _flush_output(cwd, seen, sent_at, on_output)
            if CURRENT.snapshot().suspended:
                time.sleep(0.2)
                continue
            left -= dt
            if left <= 0:
                _kill(proc, docker_name)
                _wait(proc)
                log("system", f"killed after {timeout}s")
                return 124
            time.sleep(0.1)
        _flush_output(cwd, seen, sent_at, on_output)
    finally:
        CURRENT.detach()
    for t in threads:
        t.join(timeout=2)
    return int(proc.returncode or 0)
